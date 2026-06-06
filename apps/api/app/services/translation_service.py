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
from app.services.translation_adaptation import adapt_turkish_text_preserving_semantics, build_adaptation_metadata
from app.services.transcript_quality_service import TranscriptQualityService


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
        self.transcript_quality = TranscriptQualityService()

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
            transcript_quality_score = self.transcript_quality.score(project.transcript_segments)
            transcript_quality_warning = self.transcript_quality.warning(project.transcript_segments)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.TRANSLATION_STARTED.value,
                payload_json={
                    "target_language": project.target_language,
                    "transcript_quality_score": transcript_quality_score,
                    "warning": transcript_quality_warning,
                },
            )

            self.translations.delete_for_project(project.id)

            provider = self.providers.get("TRANSLATION")
            created_segments: list[TranslationSegment] = []
            translations_by_transcript_id: dict[str, TranslationSegment] = {}
            clips_by_transcript_id = {
                clip.transcript_segment_id: clip
                for clip in self.translations.list_timeline_clips_for_project(project.id)
                if clip.transcript_segment_id
            }

            for transcript_segment in project.transcript_segments:
                source_language = transcript_segment.language_code or project.source_language or "auto"
                source_duration_ms = self._source_duration_ms(transcript_segment)
                target_duration_ms = self._target_duration_ms(transcript_segment, clips_by_transcript_id)
                result = asyncio.run(
                    provider.translate(
                        text=transcript_segment.text,
                        source_language=source_language,
                        target_language=project.target_language,
                        source_duration_ms=source_duration_ms,
                        target_duration_ms=target_duration_ms,
                    )
                )
                faithful_text = (result.get("faithful_text") or result["translated_text"]).strip()
                adaptation_result = self._adapt_translation_text(faithful_text, project.target_language, target_duration_ms)
                adapted_text = adaptation_result["adapted_text"]
                translated_text = adapted_text
                adaptation_metadata = build_adaptation_metadata(target_duration_ms, translated_text)
                translation_segment = TranslationSegment(
                    id=str(uuid7()),
                    project_id=project.id,
                    transcript_segment_id=transcript_segment.id,
                    source_language=result.get("source_language", source_language),
                    target_language=result.get("target_language", project.target_language),
                    source_text=transcript_segment.text,
                    faithful_text=faithful_text,
                    adapted_text=adapted_text,
                    translated_text=translated_text,
                    provider=result.get("provider", self.settings.translation_provider),
                    duration_target_ms=target_duration_ms,
                    semantic_similarity_score=adaptation_result["semantic_similarity_score"],
                    status=SegmentStatus.DRAFT,
                    metadata_json={
                        **result.get("metadata_json", {}),
                        **adaptation_metadata,
                        **adaptation_result,
                        "faithful_text": faithful_text,
                        "adapted_text": adapted_text,
                        "translation_stage": "faithful_then_dub_adaptation",
                        "source_duration_ms": source_duration_ms,
                        "duration_target_ms": target_duration_ms,
                    },
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
                metadata["faithful_text"] = linked_translation.faithful_text
                metadata["adapted_text"] = linked_translation.adapted_text
                metadata["semantic_similarity_score"] = float(linked_translation.semantic_similarity_score or 0)
                metadata["adaptation_rejected"] = linked_translation.metadata_json.get("adaptation_rejected")
                metadata["source_duration_ms"] = self._clip_duration_ms(clip)
                metadata["translated_duration_ms"] = linked_translation.metadata_json.get("translated_duration_ms")
                metadata["duration_match_score"] = linked_translation.metadata_json.get("duration_match_score")
                metadata["duration_target_ms"] = linked_translation.duration_target_ms
                clip.metadata_json = metadata
                clip.updated_at = datetime.now(UTC)

            job.output_json = {
                **(job.output_json or {}),
                "translation_segment_count": len(created_segments),
                "provider": created_segments[0].provider if created_segments else self.settings.translation_provider,
                "target_language": project.target_language,
                "transcript_quality_score": transcript_quality_score,
                "transcript_quality_warning": transcript_quality_warning,
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

    def _adapt_translation_text(self, translated_text: str, target_language: str, target_duration_ms: int) -> dict:
        if target_language != "tr":
            return {
                "adapted_text": translated_text,
                "semantic_similarity_score": 1.0,
                "adaptation_rejected": False,
                "semantic_similarity_threshold": 1.0,
            }
        return adapt_turkish_text_preserving_semantics(translated_text, target_duration_ms)

    def _source_duration_ms(self, transcript_segment) -> int:
        return max(int(transcript_segment.end_ms or 0) - int(transcript_segment.start_ms or 0), 1)

    def _target_duration_ms(self, transcript_segment, clips_by_transcript_id: dict) -> int:
        clip = clips_by_transcript_id.get(transcript_segment.id)
        if clip:
            return self._clip_duration_ms(clip)
        return self._source_duration_ms(transcript_segment)

    def _clip_duration_ms(self, clip) -> int:
        return max(int(clip.end_ms or 0) - int(clip.start_ms or 0), 1)
