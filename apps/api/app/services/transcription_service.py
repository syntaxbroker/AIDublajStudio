import asyncio
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import ClipType, EventType, JobState, SegmentStatus, TranscriptSource
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.timeline_clip import TimelineClip
from app.models.transcript_segment import TranscriptSegment
from app.providers.registry import ProviderRegistry
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.diarization_service import DiarizationService
from app.services.event_service import EventService
from app.services.job_service import JobService
from app.services.storage_service import StorageService
from app.services.transcript_quality_service import TranscriptQualityService
from app.services.translation_service import TranslationService


class TranscriptionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.job_service = JobService(db)
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.transcripts = TranscriptRepository(db)
        self.events = EventService(db)
        self.storage = StorageService()
        self.providers = ProviderRegistry()
        self.settings = get_settings()
        self.transcript_quality = TranscriptQualityService()
        self.diarization_service = DiarizationService(db)
        self.translation_service = TranslationService(db)

    def process_job(self, job_id: str, worker_name: str) -> None:
        job = self.jobs.get_by_id(job_id)
        if not job:
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)

        proxy_artifact_id = job.input_json["artifact_id"]
        proxy_artifact = self.artifacts.get_by_id(proxy_artifact_id)
        project = self.projects.get_by_id(job.project_id)

        try:
            if not proxy_artifact or not project:
                raise AppError("TRANSCRIBE_SOURCE_NOT_FOUND", "Proxy artifact or project not found", 404)

            proxy_path = self.storage.absolute_path(proxy_artifact.storage_path)
            if not proxy_path.exists():
                raise AppError("PROXY_VIDEO_NOT_FOUND", "Proxy video not found", 404)

            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.TRANSCRIPTION_STARTED.value,
                payload_json={"artifact_id": proxy_artifact.id},
            )

            self.transcripts.delete_clips_for_project(project.id)
            self.transcripts.delete_segments_for_project(project.id)

            provider = self.providers.get("ASR")
            requested_language = self._resolve_language_code(project.source_language)
            result = asyncio.run(
                provider.transcribe(
                    source_path=str(proxy_path),
                    language_code=requested_language,
                )
            )

            segments = result.get("segments", [])
            created_segments: list[TranscriptSegment] = []
            created_clips: list[TimelineClip] = []

            for payload in segments:
                segment = TranscriptSegment(
                    id=str(uuid7()),
                    project_id=project.id,
                    source_artifact_id=proxy_artifact.id,
                    segment_index=payload["segment_index"],
                    start_ms=payload["start_ms"],
                    end_ms=payload["end_ms"],
                    speaker_label=payload.get("speaker_label"),
                    language_code=result.get("language_code"),
                    text=payload["text"],
                    confidence=payload.get("confidence"),
                    source=TranscriptSource.ASR,
                    status=SegmentStatus.DRAFT,
                    metadata_json=payload.get("metadata_json", {}),
                )
                self.transcripts.create_segment(segment)
                created_segments.append(segment)
                self.events.publish_audit(
                    project_id=project.id,
                    actor_user_id=job.requested_by_user_id,
                    related_job_id=job.id,
                    entity_type="transcript_segment",
                    entity_id=segment.id,
                    event_type=EventType.TRANSCRIPTION_SEGMENT_CREATED.value,
                    payload_json={"segment_index": segment.segment_index, "text": segment.text},
                )

            self.db.flush()

            for segment in created_segments:
                clip = TimelineClip(
                    id=str(uuid7()),
                    project_id=project.id,
                    transcript_segment_id=segment.id,
                    artifact_id=proxy_artifact.id,
                    text=segment.text,
                    clip_type=ClipType.DIALOG,
                    track_index=0,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    lane="dialog",
                    is_locked=False,
                    metadata_json={
                        "text": segment.text,
                        "speaker_label": segment.speaker_label,
                        "source": "transcript_segment",
                    },
                )
                self.transcripts.create_clip(clip)
                created_clips.append(clip)

            transcript_quality_score = self.transcript_quality.score(created_segments)
            final_transcript = " ".join(segment.text for segment in created_segments).strip()
            detected_language = result.get("language_code")
            language_probability = result.get("language_probability")
            job.output_json = {
                **(job.output_json or {}),
                "segment_count": len(created_segments),
                "timeline_clip_count": len(created_clips),
                "transcript_source_artifact_id": proxy_artifact.id,
                "provider": result.get("provider", "mock"),
                "requested_language": requested_language,
                "detected_language": detected_language,
                "language_code": detected_language,
                "language_probability": language_probability,
                "final_transcript": final_transcript,
                "asr_device": result.get("device"),
                "asr_compute_type": result.get("compute_type"),
                "transcript_quality_score": transcript_quality_score,
            }
            job.updated_at = datetime.now(UTC)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.TRANSCRIPTION_COMPLETED.value,
                payload_json={"segment_count": len(created_segments)},
            )
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="timeline",
                entity_id=proxy_artifact.id,
                event_type=EventType.TIMELINE_CLIPS_CREATED.value,
                payload_json={"clip_count": len(created_clips)},
            )
            self.diarization_service.create_job_for_project(
                project.id,
                job.requested_by_user_id,
                proxy_artifact.id,
                parent_job_id=job.id,
                auto_commit=False,
            )
            self.translation_service.create_job_for_project(
                project.id,
                job.requested_by_user_id,
                parent_job_id=job.id,
                auto_commit=False,
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

    def _resolve_language_code(self, project_source_language: str | None) -> str:
        configured_language = (self.settings.asr_source_language or "auto").strip().lower()
        if configured_language != "auto":
            return configured_language

        project_language = (project_source_language or "auto").strip().lower()
        return project_language or "auto"
