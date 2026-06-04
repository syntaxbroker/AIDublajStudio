import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import ArtifactType, EventType, JobState, SegmentStatus
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.artifact import Artifact, ArtifactLink
from app.models.dub_segment import DubSegment
from app.providers.registry import ProviderRegistry
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.dub_repository import DubRepository
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.timeline_repository import TimelineRepository
from app.services.event_service import EventService
from app.services.job_service import JobService
from app.services.storage_service import StorageService
from app.services.voice_profile_service import VoiceProfileService


class TTSService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.job_service = JobService(db)
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.timeline = TimelineRepository(db)
        self.dubs = DubRepository(db)
        self.events = EventService(db)
        self.storage = StorageService()
        self.providers = ProviderRegistry()
        self.voice_profiles = VoiceProfileService(db)
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
        if not project.timeline_clips:
            raise AppError("TIMELINE_REQUIRED", "Timeline clips are required before TTS", 409)
        if not any((clip.translation_text or clip.text or "").strip() for clip in project.timeline_clips):
            raise AppError("TTS_SOURCE_TEXT_NOT_FOUND", "Timeline clips do not contain text for TTS", 409)
        job = self.job_service.create_tts_job(project_id, current_user_id, parent_job_id=parent_job_id)
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
            clips = self.timeline.list_clips_for_project(project.id)
            if not clips:
                raise AppError("TIMELINE_REQUIRED", "Timeline clips are required before TTS", 409)

            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.TTS_STARTED.value,
                payload_json={"clip_count": len(clips)},
            )

            self._clear_existing_outputs(project.id)
            created_segments: list[DubSegment] = []
            resolved_provider_key = self.settings.tts_provider

            for clip in clips:
                text = (clip.translation_text or clip.text or "").strip()
                if not text:
                    continue
                parent_artifact = self.artifacts.get_by_id(clip.artifact_id) if clip.artifact_id else None
                if not parent_artifact:
                    raise AppError("TTS_PARENT_ARTIFACT_NOT_FOUND", "Timeline clip parent artifact not found", 404)

                language_code = project.target_language or project.source_language or "tr"
                voice_profile, voice_name, voice_selection_source = self._resolve_voice_selection(
                    project_id=project.id,
                    character_id=clip.character_id,
                    language_code=language_code,
                    provider_key=resolved_provider_key,
                )

                result = asyncio.run(
                    self._synthesize_for_profile(
                        text=text,
                        language_code=language_code,
                        voice_name=voice_name,
                        voice_profile=voice_profile,
                    )
                )

                artifact = self._create_audio_artifact(
                    project_storage_key=project.storage_key,
                    parent_artifact=parent_artifact,
                    job_id=job.id,
                    timeline_clip_id=clip.id,
                    result=result,
                )
                segment = DubSegment(
                    id=str(uuid7()),
                    project_id=project.id,
                    translation_segment_id=clip.translation_segment_id,
                    timeline_clip_id=clip.id,
                    character_id=clip.character_id,
                    voice_profile_id=voice_profile.id if voice_profile else None,
                    text=text,
                    audio_artifact_id=artifact.id,
                    tts_artifact_id=artifact.id,
                    provider=result.get("provider", self.settings.tts_provider),
                    status=SegmentStatus.DRAFT,
                    duration_ms=result.get("duration_ms"),
                    metadata_json={
                        **result.get("metadata_json", {}),
                        "cloned": bool(voice_profile and voice_profile.profile_type == "cloned"),
                        "reference_audio_artifact_id": (
                            voice_profile.reference_audio_artifact_id if voice_profile and voice_profile.profile_type == "cloned" else None
                        ),
                        "voice_selection_source": voice_selection_source,
                        "voice_profile_id": voice_profile.id if voice_profile else None,
                        "voice_profile_display_name": voice_profile.display_name if voice_profile else None,
                        "voice_profile_type": voice_profile.profile_type if voice_profile else "default",
                    },
                )
                self.dubs.create(segment)
                self.db.flush()

                clip.dub_segment_id = segment.id
                metadata = dict(clip.metadata_json or {})
                metadata["dub_segment_id"] = segment.id
                metadata["tts_audio_artifact_id"] = artifact.id
                clip.metadata_json = metadata
                clip.updated_at = datetime.now(UTC)

                created_segments.append(segment)
                self.events.publish_audit(
                    project_id=project.id,
                    actor_user_id=job.requested_by_user_id,
                    related_job_id=job.id,
                    entity_type="dub_segment",
                    entity_id=segment.id,
                    event_type=EventType.DUB_SEGMENT_CREATED.value,
                    payload_json={"timeline_clip_id": clip.id, "text": text},
                )
                self.events.publish_audit(
                    project_id=project.id,
                    actor_user_id=job.requested_by_user_id,
                    related_job_id=job.id,
                    entity_type="artifact",
                    entity_id=artifact.id,
                    event_type=EventType.TTS_AUDIO_GENERATED.value,
                    payload_json={"timeline_clip_id": clip.id, "artifact_type": artifact.artifact_type.value},
                )

            if not created_segments:
                raise AppError("TTS_SOURCE_TEXT_NOT_FOUND", "Timeline clips do not contain text for TTS", 409)

            job.output_json = {
                **(job.output_json or {}),
                "dub_segment_count": len(created_segments),
                "artifact_count": len(created_segments),
                "provider": created_segments[0].provider if created_segments else self.settings.tts_provider,
            }
            job.updated_at = datetime.now(UTC)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.TTS_COMPLETED.value,
                payload_json={"dub_segment_count": len(created_segments)},
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

    def _resolve_voice_selection(
        self,
        *,
        project_id: str,
        character_id: str | None,
        language_code: str,
        provider_key: str,
    ):
        voice_profile, voice_name, source = self.voice_profiles.resolve_voice_for_character(
            project_id=project_id,
            character_id=character_id,
            provider=provider_key,
            language=language_code,
        )
        if voice_name:
            return voice_profile, voice_name, source

        if self.settings.tts_voice_name != "default":
            return voice_profile, self.settings.tts_voice_name, "settings_voice_name"
        if provider_key == "edge_tts":
            return voice_profile, self.settings.edge_tts_voice, "settings_edge_voice"
        return voice_profile, self.settings.tts_voice_name, "settings_default"

    async def _synthesize_for_profile(
        self,
        *,
        text: str,
        language_code: str,
        voice_name: str | None,
        voice_profile,
    ) -> dict:
        if voice_profile and voice_profile.profile_type == "cloned":
            if voice_profile.status != "ready":
                raise AppError("VOICE_PROFILE_NOT_READY", "Cloned voice profile is not ready for TTS", 409)
            if not voice_profile.reference_audio_artifact_id:
                raise AppError("VOICE_REFERENCE_NOT_FOUND", "Cloned voice profile does not have reference audio", 409)
            reference_artifact = self.artifacts.get_by_id(voice_profile.reference_audio_artifact_id)
            if not reference_artifact:
                raise AppError("VOICE_REFERENCE_NOT_FOUND", "Cloned voice reference artifact not found", 404)
            reference_path = self.storage.absolute_path(reference_artifact.storage_path)
            if not reference_path.exists():
                raise AppError("VOICE_REFERENCE_FILE_NOT_FOUND", "Cloned voice reference file not found", 404)
            reference_duration_ms = reference_artifact.duration_ms or voice_profile.sample_duration_ms or 0
            if reference_duration_ms < self.settings.voice_clone_min_sample_duration_ms:
                voice_profile.status = "failed"
                voice_profile.updated_at = datetime.now(UTC)
                raise AppError(
                    "VOICE_REFERENCE_TOO_SHORT",
                    f"Reference sample must be at least {self.settings.voice_clone_min_sample_duration_ms} ms",
                    409,
                )
            clone_provider = self.providers.get("VOICE_CLONE", voice_profile.provider or None)
            result = await clone_provider.synthesize(
                text=text,
                reference_audio_path=reference_path,
                language_code=language_code,
                voice_profile_id=voice_profile.id,
                voice_name=voice_name,
                reference_audio_artifact_id=voice_profile.reference_audio_artifact_id,
                reference_text=(
                    (reference_artifact.metadata_json or {}).get("prompt_text")
                    or (voice_profile.metadata_json or {}).get("reference_text")
                ),
            )
            metadata = dict(result.get("metadata_json", {}))
            metadata["cloned"] = True
            metadata["reference_audio_artifact_id"] = voice_profile.reference_audio_artifact_id
            metadata["voice_profile_id"] = voice_profile.id
            metadata["model_name"] = metadata.get("model_name") or voice_profile.provider or "voice_clone"
            result["metadata_json"] = metadata
            return result

        provider = self.providers.get("TTS")
        result = await provider.synthesize(
            text=text,
            language_code=language_code,
            voice_name=voice_name,
        )
        metadata = dict(result.get("metadata_json", {}))
        metadata.setdefault("cloned", False)
        result["metadata_json"] = metadata
        return result

    def _clear_existing_outputs(self, project_id: str) -> None:
        existing_segments = self.dubs.list_for_project(project_id)
        artifact_ids = {
            artifact_id
            for segment in existing_segments
            for artifact_id in [segment.audio_artifact_id, segment.tts_artifact_id]
            if artifact_id
        }
        for clip in self.timeline.list_clips_for_project(project_id):
            clip.dub_segment_id = None
            metadata = dict(clip.metadata_json or {})
            metadata.pop("dub_segment_id", None)
            metadata.pop("tts_audio_artifact_id", None)
            clip.metadata_json = metadata
            clip.updated_at = datetime.now(UTC)

        for artifact_id in artifact_ids:
            artifact = self.artifacts.get_by_id(artifact_id)
            if not artifact:
                continue
            if artifact.storage_path and self.storage.exists(artifact.storage_path):
                self.storage.delete_relative_path(artifact.storage_path)
            self.db.delete(artifact)

        self.dubs.delete_for_project(project_id)
        self.db.flush()

    def _create_audio_artifact(
        self,
        *,
        project_storage_key: str,
        parent_artifact: Artifact,
        job_id: str,
        timeline_clip_id: str,
        result: dict,
    ) -> Artifact:
        file_extension = result.get("file_extension", ".wav")
        relative_path, size_bytes, checksum = self.storage.write_bytes(
            project_storage_key,
            "tts",
            f"{timeline_clip_id}{file_extension}",
            result["audio_bytes"],
        )
        artifact = Artifact(
            id=str(uuid7()),
            project_id=parent_artifact.project_id,
            created_by_job_id=job_id,
            artifact_type=ArtifactType.TTS_AUDIO,
            storage_path=relative_path,
            file_name=Path(relative_path).name,
            mime_type=result.get("mime_type", "audio/wav"),
            size_bytes=size_bytes,
            checksum_sha256=checksum,
            duration_ms=result.get("duration_ms"),
            metadata_json=result.get("metadata_json", {}),
        )
        self.artifacts.create(artifact)
        self.artifacts.create_link(
            ArtifactLink(
                id=str(uuid7()),
                parent_artifact_id=parent_artifact.id,
                child_artifact_id=artifact.id,
                relation="derived_from",
            )
        )
        self.db.flush()
        return artifact
