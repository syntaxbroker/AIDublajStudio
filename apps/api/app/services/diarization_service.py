import asyncio
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.enums import EventType, JobState
from app.core.uuid7 import uuid7
from app.models.speaker_segment import SpeakerSegment
from app.providers.registry import ProviderRegistry
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.speaker_repository import SpeakerRepository
from app.services.event_service import EventService
from app.services.job_service import JobService
from app.services.storage_service import StorageService


class DiarizationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.job_service = JobService(db)
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.speakers = SpeakerRepository(db)
        self.events = EventService(db)
        self.storage = StorageService()
        self.providers = ProviderRegistry()

    def create_job_for_project(
        self,
        project_id: str,
        current_user_id: str,
        artifact_id: str,
        parent_job_id: str | None = None,
        *,
        auto_commit: bool = True,
    ):
        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
        if not project.transcript_segments:
            raise AppError("TRANSCRIPT_REQUIRED", "Transcript segments are required before diarization", 409)
        job = self.job_service.create_diarize_job(project_id, current_user_id, artifact_id, parent_job_id=parent_job_id)
        if auto_commit:
            self.db.commit()
            self.db.refresh(job)
        return job

    def process_job(self, job_id: str, worker_name: str) -> None:
        job = self.jobs.get_by_id(job_id)
        if not job:
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)

        artifact_id = job.input_json["artifact_id"]
        artifact = self.artifacts.get_by_id(artifact_id)
        project = self.projects.get_by_id(job.project_id)

        try:
            if not artifact or not project:
                raise AppError("DIARIZATION_SOURCE_NOT_FOUND", "Diarization source artifact or project not found", 404)
            if not project.transcript_segments:
                raise AppError("TRANSCRIPT_REQUIRED", "Transcript segments are required before diarization", 409)

            source_path = self.storage.absolute_path(artifact.storage_path)
            if not source_path.exists():
                raise AppError("DIARIZATION_SOURCE_FILE_NOT_FOUND", "Diarization source file not found", 404)

            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.DIARIZATION_STARTED.value,
                payload_json={"artifact_id": artifact.id},
            )

            self.speakers.delete_for_project(project.id)

            provider = self.providers.get("DIARIZATION")
            result = asyncio.run(provider.diarize(str(source_path)))

            created_segments: list[SpeakerSegment] = []
            for payload in result.get("segments", []):
                speaker_segment = SpeakerSegment(
                    id=str(uuid7()),
                    project_id=project.id,
                    start_ms=payload["start_ms"],
                    end_ms=payload["end_ms"],
                    speaker_label=payload["speaker_label"],
                    confidence=payload.get("confidence"),
                    provider=result.get("provider"),
                    metadata_json=payload.get("metadata_json", {}),
                )
                self.speakers.create(speaker_segment)
                created_segments.append(speaker_segment)
                self.events.publish_audit(
                    project_id=project.id,
                    actor_user_id=job.requested_by_user_id,
                    related_job_id=job.id,
                    entity_type="speaker_segment",
                    entity_id=speaker_segment.id,
                    event_type=EventType.SPEAKER_SEGMENT_CREATED.value,
                    payload_json={"speaker_label": speaker_segment.speaker_label},
                )

            self.db.flush()

            transcript_segments = self.speakers.list_transcript_segments_for_project(project.id)
            clips = self.speakers.list_timeline_clips_for_project(project.id)
            assigned_count = 0

            for transcript_segment in transcript_segments:
                speaker_label = self._best_overlap_speaker(transcript_segment.start_ms, transcript_segment.end_ms, created_segments)
                transcript_segment.speaker_label = speaker_label
                transcript_segment.updated_at = datetime.now(UTC)
                if speaker_label:
                    assigned_count += 1
                    self.events.publish_audit(
                        project_id=project.id,
                        actor_user_id=job.requested_by_user_id,
                        related_job_id=job.id,
                        entity_type="transcript_segment",
                        entity_id=transcript_segment.id,
                        event_type=EventType.TRANSCRIPT_SPEAKER_ASSIGNED.value,
                        payload_json={"speaker_label": speaker_label},
                    )

            speaker_by_transcript_id = {segment.id: segment.speaker_label for segment in transcript_segments}
            for clip in clips:
                clip.speaker_label = speaker_by_transcript_id.get(clip.transcript_segment_id)
                metadata = dict(clip.metadata_json or {})
                metadata["speaker_label"] = clip.speaker_label
                clip.metadata_json = metadata
                clip.updated_at = datetime.now(UTC)

            job.output_json = {
                **(job.output_json or {}),
                "speaker_segment_count": len(created_segments),
                "assigned_transcript_count": assigned_count,
                "provider": result.get("provider", "mock"),
                "device": result.get("device"),
                "model_load_time_ms": result.get("model_load_time_ms"),
                "inference_time_ms": result.get("inference_time_ms"),
                "source_duration_ms": result.get("source_duration_ms"),
                "prepared_duration_ms": result.get("prepared_duration_ms"),
                "source_audio_padded_ms": result.get("source_audio_padded_ms"),
            }
            job.updated_at = datetime.now(UTC)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.DIARIZATION_COMPLETED.value,
                payload_json={"speaker_segment_count": len(created_segments)},
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

    def _best_overlap_speaker(self, start_ms: int, end_ms: int, speaker_segments: list[SpeakerSegment]) -> str | None:
        best_label = None
        best_overlap = 0
        for speaker_segment in speaker_segments:
            overlap = min(end_ms, speaker_segment.end_ms) - max(start_ms, speaker_segment.start_ms)
            if overlap > best_overlap:
                best_overlap = overlap
                best_label = speaker_segment.speaker_label
        return best_label
