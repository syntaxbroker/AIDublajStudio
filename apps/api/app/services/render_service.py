from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.enums import ArtifactType, EventType, JobState
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.artifact import Artifact, ArtifactLink
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.services.event_service import EventService
from app.services.ffmpeg_service import FFmpegService
from app.services.ffprobe_service import FFProbeService
from app.services.job_service import JobService
from app.services.storage_service import StorageService


class RenderService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.job_service = JobService(db)
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.events = EventService(db)
        self.storage = StorageService()
        self.ffmpeg = FFmpegService()
        self.ffprobe = FFProbeService()

    def create_job_for_project(
        self,
        project_id: str,
        current_user_id: str,
        parent_job_id: str | None = None,
        *,
        auto_commit: bool = True,
    ):
        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
        job = self.job_service.create_render_job(project_id, current_user_id, parent_job_id=parent_job_id)
        if auto_commit:
            self.db.commit()
            self.db.refresh(job)
        return job

    def process_job(self, job_id: str, worker_name: str) -> None:
        job = self.jobs.get_by_id(job_id)
        if not job:
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)

        project = self.projects.get_by_id(job.project_id)
        try:
            if not project:
                raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)

            final_dub_audio = self._resolve_final_dub_audio(project.id)
            video_source = self._resolve_video_source(project.id)
            audio_path = self.storage.absolute_path(final_dub_audio.storage_path)
            video_path = self.storage.absolute_path(video_source.storage_path)

            if not audio_path.exists():
                raise AppError("FINAL_DUB_AUDIO_FILE_NOT_FOUND", "Final dub audio file not found", 404)
            if not video_path.exists():
                raise AppError("VIDEO_SOURCE_FILE_NOT_FOUND", "Render video source file not found", 404)

            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.RENDER_STARTED.value,
                payload_json={"video_source_artifact_id": video_source.id, "audio_artifact_id": final_dub_audio.id},
            )

            self._delete_existing_final_render(project.id)
            output_path = self.storage.ensure_project_structure(project.storage_key) / "renders" / f"{uuid7()}-final-render.mp4"
            self.ffmpeg.render_video_with_audio(video_path, audio_path, output_path)
            metadata = self.ffprobe.probe(output_path)
            payload = output_path.read_bytes()

            artifact = Artifact(
                id=str(uuid7()),
                project_id=project.id,
                created_by_job_id=job.id,
                artifact_type=ArtifactType.FINAL_RENDER,
                storage_path=output_path.relative_to(self.storage.root).as_posix(),
                file_name=output_path.name,
                mime_type="video/mp4",
                size_bytes=len(payload),
                checksum_sha256=self._sha256(payload),
                duration_ms=self._duration_ms(metadata),
                width=self._width(metadata),
                height=self._height(metadata),
                frame_rate=self._frame_rate(metadata),
                audio_channels=self._audio_channels(metadata),
                sample_rate=self._sample_rate(metadata),
                metadata_json=metadata,
            )
            self.artifacts.create(artifact)
            self.db.flush()

            for parent_artifact in [video_source, final_dub_audio]:
                self.artifacts.create_link(
                    ArtifactLink(
                        id=str(uuid7()),
                        parent_artifact_id=parent_artifact.id,
                        child_artifact_id=artifact.id,
                        relation="rendered_from",
                    )
                )

            job.output_json = {
                **(job.output_json or {}),
                "final_render_artifact_id": artifact.id,
                "video_source_artifact_id": video_source.id,
                "audio_artifact_id": final_dub_audio.id,
            }
            job.updated_at = datetime.now(UTC)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=artifact.id,
                event_type=EventType.RENDER_COMPLETED.value,
                payload_json={"artifact_type": artifact.artifact_type.value},
            )
            self.job_service.transition(job, JobState.COMPLETED, worker_name=worker_name)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            failed_job = self.jobs.get_by_id(job_id)
            if failed_job:
                failed_job.error_json = {"message": str(exc)}
                self.job_service.transition(failed_job, JobState.FAILED, worker_name=worker_name, error_message=str(exc))
            self.db.commit()
            raise

    def _resolve_final_dub_audio(self, project_id: str) -> Artifact:
        artifacts = self.artifacts.list_for_project(project_id)
        artifact = next((item for item in artifacts if item.artifact_type == ArtifactType.FINAL_DUB_AUDIO), None)
        if not artifact:
            raise AppError("FINAL_DUB_AUDIO_NOT_FOUND", "Final dub audio artifact not found", 404)
        return artifact

    def _resolve_video_source(self, project_id: str) -> Artifact:
        artifacts = self.artifacts.list_for_project(project_id)
        source_video = next((item for item in artifacts if item.artifact_type == ArtifactType.SOURCE_VIDEO), None)
        if source_video:
            return source_video
        proxy_video = next((item for item in artifacts if item.artifact_type == ArtifactType.PROXY_VIDEO), None)
        if proxy_video:
            return proxy_video
        raise AppError("RENDER_VIDEO_SOURCE_NOT_FOUND", "Render video source not found", 404)

    def _delete_existing_final_render(self, project_id: str) -> None:
        existing = [
            artifact
            for artifact in self.artifacts.list_for_project(project_id)
            if artifact.artifact_type == ArtifactType.FINAL_RENDER
        ]
        for artifact in existing:
            if artifact.storage_path and self.storage.exists(artifact.storage_path):
                self.storage.delete_relative_path(artifact.storage_path)
            self.db.delete(artifact)
        self.db.flush()

    def _duration_ms(self, metadata: dict) -> int | None:
        duration = metadata.get("format", {}).get("duration")
        if duration is None:
            return None
        return int(float(duration) * 1000)

    def _video_stream(self, metadata: dict) -> dict:
        return next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"), {})

    def _audio_stream(self, metadata: dict) -> dict:
        return next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "audio"), {})

    def _width(self, metadata: dict) -> int | None:
        return self._video_stream(metadata).get("width")

    def _height(self, metadata: dict) -> int | None:
        return self._video_stream(metadata).get("height")

    def _frame_rate(self, metadata: dict) -> float | None:
        rate = self._video_stream(metadata).get("avg_frame_rate", "0/1")
        try:
            numerator, denominator = rate.split("/")
            denominator_value = float(denominator)
            if not denominator_value:
                return None
            return round(float(numerator) / denominator_value, 3)
        except Exception:
            return None

    def _audio_channels(self, metadata: dict) -> int | None:
        return self._audio_stream(metadata).get("channels")

    def _sample_rate(self, metadata: dict) -> int | None:
        sample_rate = self._audio_stream(metadata).get("sample_rate")
        return int(sample_rate) if sample_rate else None

    def _sha256(self, payload: bytes) -> str:
        import hashlib

        return hashlib.sha256(payload).hexdigest()
