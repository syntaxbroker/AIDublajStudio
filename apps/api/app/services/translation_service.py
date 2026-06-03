import asyncio
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import EventType, JobState, SegmentStatus
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.translation_segment import TranslationSegment
from app.providers.registry import ProviderRegistry
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.translation_repository import TranslationRepository
from app.services.event_service import EventService
from app.services.job_service import JobService


class TranslationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.job_service = JobService(db)
        self.projects = ProjectRepository(db)
        self.translations = TranslationRepository(db)
        self.events = EventService(db)
        self.providers = ProviderRegistry()
        self.settings = get_settings()

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
        if not project.transcript_segments:
            raise AppError("TRANSCRIPT_REQUIRED", "Transcript segments are required before translation", 409)
        job = self.job_service.create_translate_job(project_id, current_user_id, parent_job_id=parent_job_id)
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
            if not project.transcript_segments:
                raise AppError("TRANSCRIPT_REQUIRED", "Transcript segments are required before translation", 409)

            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.TRANSLATION_STARTED.value,
                payload_json={"target_language": project.target_language},
            )

            self.translations.delete_for_project(project.id)

            provider = self.providers.get("TRANSLATION")
            created_segments: list[TranslationSegment] = []
            translations_by_transcript_id: dict[str, TranslationSegment] = {}

            for transcript_segment in project.transcript_segments:
                source_language = transcript_segment.language_code or project.source_language or "auto"
                result = asyncio.run(
                    provider.translate(
                        text=transcript_segment.text,
                        source_language=source_language,
                        target_language=project.target_language,
                    )
                )
                translation_segment = TranslationSegment(
                    id=str(uuid7()),
                    project_id=project.id,
                    transcript_segment_id=transcript_segment.id,
                    source_language=result.get("source_language", source_language),
                    target_language=result.get("target_language", project.target_language),
                    source_text=transcript_segment.text,
                    translated_text=result["translated_text"],
                    provider=result.get("provider", self.settings.translation_provider),
                    status=SegmentStatus.DRAFT,
                    metadata_json=result.get("metadata_json", {}),
                )
                self.translations.create(translation_segment)
                created_segments.append(translation_segment)
                translations_by_transcript_id[transcript_segment.id] = translation_segment
                self.events.publish_audit(
                    project_id=project.id,
                    actor_user_id=job.requested_by_user_id,
                    related_job_id=job.id,
                    entity_type="translation_segment",
                    entity_id=translation_segment.id,
                    event_type=EventType.TRANSLATION_SEGMENT_CREATED.value,
                    payload_json={"transcript_segment_id": transcript_segment.id},
                )

            self.db.flush()

            for clip in self.translations.list_timeline_clips_for_project(project.id):
                if not clip.transcript_segment_id:
                    continue
                linked_translation = translations_by_transcript_id.get(clip.transcript_segment_id)
                if not linked_translation:
                    continue
                clip.translation_segment_id = linked_translation.id
                clip.translation_text = linked_translation.translated_text
                metadata = dict(clip.metadata_json or {})
                metadata["translated_text"] = linked_translation.translated_text
                clip.metadata_json = metadata
                clip.updated_at = datetime.now(UTC)

            job.output_json = {
                **(job.output_json or {}),
                "translation_segment_count": len(created_segments),
                "provider": created_segments[0].provider if created_segments else self.settings.translation_provider,
                "target_language": project.target_language,
            }
            job.updated_at = datetime.now(UTC)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.TRANSLATION_COMPLETED.value,
                payload_json={"translation_segment_count": len(created_segments)},
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
