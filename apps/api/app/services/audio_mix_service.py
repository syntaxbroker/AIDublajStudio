from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.enums import ArtifactType, EventType, JobState
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.artifact import Artifact, ArtifactLink
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.dub_repository import DubRepository
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.timeline_repository import TimelineRepository
from app.services.event_service import EventService
from app.services.ffmpeg_service import FFmpegService
from app.services.ffprobe_service import FFProbeService
from app.services.job_service import JobService
from app.services.storage_service import StorageService


class AudioMixService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.job_service = JobService(db)
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.dubs = DubRepository(db)
        self.timeline = TimelineRepository(db)
        self.events = EventService(db)
        self.ffmpeg = FFmpegService()
        self.ffprobe = FFProbeService()
        self.storage = StorageService()

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
        if not project.dub_segments:
            raise AppError("DUB_SEGMENTS_REQUIRED", "Dub segments are required before audio mix", 409)
        job = self.job_service.create_audio_mix_job(project_id, current_user_id, parent_job_id=parent_job_id)
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
            if not project.dub_segments:
                raise AppError("DUB_SEGMENTS_REQUIRED", "Dub segments are required before audio mix", 409)

            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.AUDIO_MIX_STARTED.value,
                payload_json={"dub_segment_count": len(project.dub_segments)},
            )

            self._delete_existing_final_mix(project.id)

            clip_map = {clip.id: clip for clip in self.timeline.list_clips_for_project(project.id)}
            prepared_segments: list[dict] = []

            for dub_segment in sorted(project.dub_segments, key=lambda item: clip_map.get(item.timeline_clip_id).start_ms if item.timeline_clip_id in clip_map else 0):
                clip = clip_map.get(dub_segment.timeline_clip_id)
                if not clip:
                    raise AppError("TIMELINE_CLIP_NOT_FOUND", "Timeline clip for dub segment not found", 404)
                if not dub_segment.audio_artifact_id:
                    raise AppError("TTS_AUDIO_NOT_FOUND", "Dub segment audio artifact not found", 404)

                artifact = self.artifacts.get_by_id(dub_segment.audio_artifact_id)
                if not artifact:
                    raise AppError("TTS_AUDIO_NOT_FOUND", "Dub segment audio artifact not found", 404)

                source_path = self.storage.absolute_path(artifact.storage_path)
                if not source_path.exists():
                    raise AppError("TTS_AUDIO_FILE_NOT_FOUND", "Dub segment audio file not found", 404)

                prepared_segments.append(
                    {
                        "dub_segment_id": dub_segment.id,
                        "artifact_id": artifact.id,
                        "source_path": source_path,
                        "start_ms": clip.start_ms,
                        "end_ms": clip.end_ms,
                        "clip_duration_ms": clip.end_ms - clip.start_ms,
                    }
                )

            if not prepared_segments:
                raise AppError("DUB_SEGMENTS_REQUIRED", "Dub segments are required before audio mix", 409)

            self._validate_no_overlap(prepared_segments)
            total_duration_ms = max(segment["end_ms"] for segment in prepared_segments)
            output_path = self.storage.ensure_project_structure(project.storage_key) / "audio" / f"{uuid7()}-final-dub.wav"
            self.ffmpeg.mix_audio_segments(prepared_segments, output_path, total_duration_ms)
            metadata = self.ffprobe.probe(output_path)
            payload = output_path.read_bytes()

            artifact = Artifact(
                id=str(uuid7()),
                project_id=project.id,
                created_by_job_id=job.id,
                artifact_type=ArtifactType.FINAL_DUB_AUDIO,
                storage_path=output_path.relative_to(self.storage.root).as_posix(),
                file_name=output_path.name,
                mime_type="audio/wav",
                size_bytes=len(payload),
                checksum_sha256=self._sha256(payload),
                duration_ms=self._duration_ms(metadata),
                audio_channels=self._audio_channels(metadata),
                sample_rate=self._sample_rate(metadata),
                metadata_json=metadata,
            )
            self.artifacts.create(artifact)
            self.db.flush()

            for segment in prepared_segments:
                self.artifacts.create_link(
                    ArtifactLink(
                        id=str(uuid7()),
                        parent_artifact_id=segment["artifact_id"],
                        child_artifact_id=artifact.id,
                        relation="mixed_from",
                    )
                )
                self.events.publish_audit(
                    project_id=project.id,
                    actor_user_id=job.requested_by_user_id,
                    related_job_id=job.id,
                    entity_type="dub_segment",
                    entity_id=segment["dub_segment_id"],
                    event_type=EventType.AUDIO_SEGMENT_PLACED.value,
                    payload_json={"start_ms": segment["start_ms"], "end_ms": segment["end_ms"], "artifact_id": segment["artifact_id"]},
                )

            job.output_json = {
                **(job.output_json or {}),
                "final_audio_artifact_id": artifact.id,
                "segment_count": len(prepared_segments),
                "duration_ms": artifact.duration_ms,
            }
            job.updated_at = datetime.now(UTC)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=artifact.id,
                event_type=EventType.AUDIO_MIX_COMPLETED.value,
                payload_json={"artifact_type": artifact.artifact_type.value, "duration_ms": artifact.duration_ms},
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

    def _delete_existing_final_mix(self, project_id: str) -> None:
        existing = [
            artifact
            for artifact in self.artifacts.list_for_project(project_id)
            if artifact.artifact_type == ArtifactType.FINAL_DUB_AUDIO
        ]
        for artifact in existing:
            if artifact.storage_path and self.storage.exists(artifact.storage_path):
                self.storage.delete_relative_path(artifact.storage_path)
            self.db.delete(artifact)
        self.db.flush()

    def _validate_no_overlap(self, segments: list[dict]) -> None:
        ordered_segments = sorted(segments, key=lambda item: item["start_ms"])
        for left, right in zip(ordered_segments, ordered_segments[1:], strict=False):
            if right["start_ms"] < left["end_ms"]:
                raise AppError("AUDIO_MIX_OVERLAP_NOT_SUPPORTED", "Overlapping dub segments are not supported for audio mix", 409)

    def _duration_ms(self, metadata: dict) -> int | None:
        duration = metadata.get("format", {}).get("duration")
        if duration is None:
            return None
        return int(float(duration) * 1000)

    def _audio_channels(self, metadata: dict) -> int | None:
        audio = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "audio"), {})
        return audio.get("channels")

    def _sample_rate(self, metadata: dict) -> int | None:
        audio = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "audio"), {})
        return int(audio["sample_rate"]) if audio.get("sample_rate") else None

    def _sha256(self, payload: bytes) -> str:
        import hashlib

        return hashlib.sha256(payload).hexdigest()
