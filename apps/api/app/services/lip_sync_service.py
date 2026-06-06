import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.enums import ArtifactType, EventType, JobState, JobType
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.artifact import Artifact, ArtifactLink
from app.providers.registry import ProviderRegistry
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.services.event_service import EventService
from app.services.ffprobe_service import FFProbeService
from app.services.job_service import JobService
from app.services.storage_service import StorageService


logger = logging.getLogger(__name__)


class LipSyncService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.job_service = JobService(db)
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.events = EventService(db)
        self.providers = ProviderRegistry()
        self.storage = StorageService()
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

        active = self._active_job(project_id)
        if active:
            return active

        completed = self._completed_job(project_id)
        if completed:
            return completed

        job = self.job_service.create_lip_sync_job(project_id, current_user_id, parent_job_id=parent_job_id)
        if auto_commit:
            self.db.commit()
            self.db.refresh(job)
        return job

    def process_job(self, job_id: str, worker_name: str) -> None:
        logger.info("LIP_SYNC job picked by worker", extra={"job_id": job_id, "worker_name": worker_name})
        job = self.jobs.get_by_id(job_id)
        if not job:
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)

        project = self.projects.get_by_id(job.project_id)
        try:
            if not project:
                raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)

            logger.info("Updating state to PROCESSING", extra={"job_id": job.id, "worker_name": worker_name})
            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self.db.commit()
            self.db.refresh(job)

            existing_artifact = self._existing_lipsync_artifact(project.id)
            if existing_artifact:
                if self._is_lipsync_current(project.id, existing_artifact):
                    job.output_json = {
                        **(job.output_json or {}),
                        "lipsync_video_artifact_id": existing_artifact.id,
                        "reused": True,
                    }
                    job.updated_at = datetime.now(UTC)
                    self.job_service.transition(job, JobState.COMPLETED, worker_name=worker_name)
                    self.db.commit()
                    return
                self._delete_lipsync_artifacts(project.id)

            final_dub_audio = self._resolve_final_dub_audio(project.id)
            video_source = self._resolve_video_source(project.id)
            audio_path = self.storage.absolute_path(final_dub_audio.storage_path)
            video_path = self.storage.absolute_path(video_source.storage_path)

            if not audio_path.exists():
                raise AppError("FINAL_DUB_AUDIO_FILE_NOT_FOUND", "Final dub audio file not found", 404)
            if not video_path.exists():
                raise AppError("LIP_SYNC_VIDEO_SOURCE_FILE_NOT_FOUND", "Lip sync video source file not found", 404)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.LIP_SYNC_STARTED.value,
                payload_json={"video_source_artifact_id": video_source.id, "audio_artifact_id": final_dub_audio.id},
            )
            self.db.commit()
            self.db.refresh(job)

            provider = self.providers.get("LIP_SYNC")
            output_path = self.storage.ensure_project_structure(project.storage_key) / "lipsync" / f"{uuid7()}-lipsync.mp4"
            logger.info("Starting MuseTalk execution", extra={"job_id": job.id, "output_path": str(output_path)})
            self.job_service.append_log(
                job,
                "Starting MuseTalk execution",
                {
                    "video_source_artifact_id": video_source.id,
                    "audio_artifact_id": final_dub_audio.id,
                    "output_path": str(output_path),
                },
            )
            self.db.commit()
            provider_metadata = await_result(
                provider.render(video_path=video_path, audio_path=audio_path, output_path=output_path)
            )
            logger.info("MuseTalk execution completed", extra={"job_id": job.id, "output_path": str(output_path)})
            self.job_service.append_log(job, "MuseTalk execution completed", {"output_path": str(output_path)})

            service_metadata = provider_metadata.get("service_metadata") or {}
            output_report = service_metadata.get("output") or {}
            temporal_validation = service_metadata.get("temporal_validation") or {}
            raw_temporal_report = temporal_validation.get("raw_output") or {}
            self._validate_provider_temporal_metadata(provider_metadata, raw_temporal_report)

            metadata = self.ffprobe.probe(output_path)
            self._validate_resolution_preservation(video_source, metadata)
            output_resolution = self._resolution_label(output_report) or self._resolution_label_from_probe(metadata)
            output_fps = output_report.get("fps") or self._frame_rate(metadata)
            input_resolution = self._resolution_label_from_artifact(video_source)
            payload = output_path.read_bytes()
            artifact = Artifact(
                id=str(uuid7()),
                project_id=project.id,
                created_by_job_id=job.id,
                artifact_type=ArtifactType.LIPSYNC_VIDEO,
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
                metadata_json={
                    **metadata,
                    "provider": provider_metadata.get("provider", "mock"),
                    "mock": bool(provider_metadata.get("mock", provider_metadata.get("provider") == "mock")),
                    "fps": output_fps,
                    "resolution": output_resolution,
                    "source_width": video_source.width,
                    "source_height": video_source.height,
                    "working_width": self._width(metadata),
                    "working_height": self._height(metadata),
                    "source_resolution": input_resolution,
                    "lipsync_resolution": output_resolution,
                    "resolution_preserved": input_resolution == output_resolution,
                    "resolution_preservation_policy": "source",
                    "processing_time_ms": service_metadata.get("processing_time_ms"),
                    "source_video_artifact_id": video_source.id,
                    "audio_artifact_id": final_dub_audio.id,
                    "quality_preset": service_metadata.get("quality_preset")
                    or provider_metadata.get("quality_preset")
                    or "mock",
                    "face_crop_detection_status": service_metadata.get("face_crop_detection_status"),
                    "raw_output_duration_ms": raw_temporal_report.get("raw_output_duration_ms"),
                    "raw_output_frame_count": raw_temporal_report.get("raw_output_frame_count"),
                    "raw_output_fps": raw_temporal_report.get("raw_output_fps"),
                    "expected_duration_ms": raw_temporal_report.get("expected_duration_ms"),
                    "expected_frame_count": raw_temporal_report.get("expected_frame_count"),
                    "freeze_detected": raw_temporal_report.get("freeze_detected"),
                    "freeze_start_frame": raw_temporal_report.get("freeze_start_frame"),
                    "freeze_start_ms": raw_temporal_report.get("freeze_start_ms"),
                    "overall_static_ratio": raw_temporal_report.get("overall_static_ratio")
                    or raw_temporal_report.get("adjacent_static_frame_ratio"),
                    "speaker_static_ratio": raw_temporal_report.get("speaker_static_ratio"),
                    "longest_static_run": raw_temporal_report.get("longest_static_run"),
                    "overall_longest_static_run": raw_temporal_report.get("overall_longest_static_run"),
                    "static_validation_status": raw_temporal_report.get("static_validation_status"),
                    "intro_static_ratio": raw_temporal_report.get("intro_static_ratio"),
                    "outro_static_ratio": raw_temporal_report.get("outro_static_ratio"),
                    "chunk_mode": temporal_validation.get("chunk_mode", False),
                    "chunk_seconds": temporal_validation.get("chunk_seconds"),
                    "chunk_overlap_ms": temporal_validation.get("chunk_overlap_ms"),
                    "chunk_count": temporal_validation.get("chunk_count"),
                    "failed_chunk_index": temporal_validation.get("failed_chunk_index"),
                    "per_chunk_duration_ms": temporal_validation.get("per_chunk_duration_ms"),
                    "per_chunk_static_ratio": temporal_validation.get("per_chunk_static_ratio"),
                    "concat_method": temporal_validation.get("concat_method"),
                    "musetalk_report": service_metadata,
                    "lip_sync_provider": provider_metadata,
                },
            )
            self.artifacts.create(artifact)
            self.db.flush()

            for parent_artifact in [video_source, final_dub_audio]:
                self.artifacts.create_link(
                    ArtifactLink(
                        id=str(uuid7()),
                        parent_artifact_id=parent_artifact.id,
                        child_artifact_id=artifact.id,
                        relation="lipsynced_from",
                    )
                )

            job.output_json = {
                **(job.output_json or {}),
                "lipsync_video_artifact_id": artifact.id,
                "video_source_artifact_id": video_source.id,
                "audio_artifact_id": final_dub_audio.id,
                "quality_preset": artifact.metadata_json.get("quality_preset"),
                "processing_time_ms": artifact.metadata_json.get("processing_time_ms"),
            }
            job.updated_at = datetime.now(UTC)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=artifact.id,
                event_type=EventType.LIP_SYNC_COMPLETED.value,
                payload_json={"artifact_type": artifact.artifact_type.value},
            )
            logger.info("Updating state to COMPLETED", extra={"job_id": job.id, "worker_name": worker_name})
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

    def _active_job(self, project_id: str):
        for job in self.jobs.list_for_project(project_id):
            if job.job_type == JobType.LIP_SYNC and job.state in {
                JobState.PENDING,
                JobState.QUEUED,
                JobState.PROCESSING,
            }:
                return job
        return None

    def _completed_job(self, project_id: str):
        existing_artifact = self._existing_lipsync_artifact(project_id)
        if not existing_artifact or not self._is_lipsync_current(project_id, existing_artifact):
            return None
        for job in self.jobs.list_for_project(project_id):
            if job.job_type == JobType.LIP_SYNC and job.state == JobState.COMPLETED:
                return job
        return None

    def _existing_lipsync_artifact(self, project_id: str) -> Artifact | None:
        return next(
            (item for item in self.artifacts.list_for_project(project_id) if item.artifact_type == ArtifactType.LIPSYNC_VIDEO),
            None,
        )

    def _delete_lipsync_artifacts(self, project_id: str) -> None:
        for artifact in [
            item
            for item in self.artifacts.list_for_project(project_id)
            if item.artifact_type == ArtifactType.LIPSYNC_VIDEO
        ]:
            if artifact.storage_path and self.storage.exists(artifact.storage_path):
                self.storage.delete_relative_path(artifact.storage_path)
            self.db.delete(artifact)
        self.db.flush()

    def _is_lipsync_current(self, project_id: str, artifact: Artifact) -> bool:
        final_dub_audio = next(
            (
                item
                for item in self.artifacts.list_for_project(project_id)
                if item.artifact_type == ArtifactType.FINAL_DUB_AUDIO
            ),
            None,
        )
        if not final_dub_audio:
            return False
        metadata = artifact.metadata_json or {}
        if metadata.get("audio_artifact_id") == final_dub_audio.id:
            return True
        if artifact.created_at and final_dub_audio.created_at:
            return artifact.created_at >= final_dub_audio.created_at
        return False

    def _resolve_final_dub_audio(self, project_id: str) -> Artifact:
        artifact = next(
            (item for item in self.artifacts.list_for_project(project_id) if item.artifact_type == ArtifactType.FINAL_DUB_AUDIO),
            None,
        )
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
        raise AppError("LIP_SYNC_VIDEO_SOURCE_NOT_FOUND", "Lip sync video source not found", 404)

    def _duration_ms(self, metadata: dict) -> int | None:
        duration = metadata.get("format", {}).get("duration")
        return int(float(duration) * 1000) if duration is not None else None

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
            return round(float(numerator) / denominator_value, 3) if denominator_value else None
        except Exception:
            return None

    def _audio_channels(self, metadata: dict) -> int | None:
        return self._audio_stream(metadata).get("channels")

    def _sample_rate(self, metadata: dict) -> int | None:
        sample_rate = self._audio_stream(metadata).get("sample_rate")
        return int(sample_rate) if sample_rate else None

    def _resolution_label(self, report: dict) -> str | None:
        width = report.get("width")
        height = report.get("height")
        if width and height:
            return f"{width}x{height}"
        return None

    def _resolution_label_from_probe(self, metadata: dict) -> str | None:
        video_stream = self._video_stream(metadata)
        width = video_stream.get("width")
        height = video_stream.get("height")
        if width and height:
            return f"{width}x{height}"
        return None

    def _validate_provider_temporal_metadata(self, provider_metadata: dict, raw_temporal_report: dict) -> None:
        if provider_metadata.get("provider") != "musetalk":
            return
        if not raw_temporal_report:
            raise AppError(
                "MUSETALK_TEMPORAL_METADATA_MISSING",
                "MuseTalk response did not include raw temporal validation metadata",
                502,
            )
        if raw_temporal_report.get("freeze_detected"):
            raise AppError(
                "MUSETALK_FREEZE_DETECTED",
                "MuseTalk raw output contains frozen/static frames",
                502,
            )
        raw_frames = raw_temporal_report.get("raw_output_frame_count")
        expected_frames = raw_temporal_report.get("expected_frame_count")
        if raw_frames is not None and expected_frames is not None and int(raw_frames) + 2 < int(expected_frames):
            raise AppError(
                "MUSETALK_SHORT_OUTPUT",
                f"MuseTalk raw output is shorter than expected: {raw_frames}/{expected_frames} frames",
                502,
            )

    def _validate_resolution_preservation(self, video_source: Artifact, metadata: dict) -> None:
        output_width = self._width(metadata)
        output_height = self._height(metadata)
        if not video_source.width or not video_source.height or not output_width or not output_height:
            return
        if output_width != video_source.width or output_height != video_source.height:
            raise AppError(
                "LIPSYNC_RESOLUTION_MISMATCH",
                (
                    "Lip sync output resolution does not match input video. "
                    f"Input: {video_source.width}x{video_source.height}. "
                    f"Output: {output_width}x{output_height}."
                ),
                502,
            )

    def _resolution_label_from_artifact(self, artifact: Artifact) -> str | None:
        if artifact.width and artifact.height:
            return f"{artifact.width}x{artifact.height}"
        return None

    def _sha256(self, payload: bytes) -> str:
        import hashlib

        return hashlib.sha256(payload).hexdigest()


def await_result(awaitable):
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    return loop.run_until_complete(awaitable)
