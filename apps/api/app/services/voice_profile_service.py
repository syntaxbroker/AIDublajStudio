from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import EventType
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.voice_profile import CharacterVoiceAssignment, VoiceProfile
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.character_repository import CharacterRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.voice_profile_repository import VoiceProfileRepository
from app.schemas.voice_profile import (
    CharacterVoiceAssignmentRequest,
    VoiceProfileCreateRequest,
    VoiceProfileResponse,
    VoiceProfileUpdateRequest,
)
from app.services.event_service import EventService
from app.services.storage_service import StorageService
from app.services.voice_similarity_service import VoiceSimilarityService


class VoiceProfileService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.characters = CharacterRepository(db)
        self.voice_profiles = VoiceProfileRepository(db)
        self.events = EventService(db)
        self.settings = get_settings()
        self.storage = StorageService()
        self.voice_similarity = VoiceSimilarityService()

    def list_profiles(self) -> list[VoiceProfileResponse]:
        return [VoiceProfileResponse.model_validate(item) for item in self.voice_profiles.list_profiles()]

    def create_profile(self, payload: VoiceProfileCreateRequest, current_user_id: str | None = None) -> VoiceProfileResponse:
        del current_user_id
        existing = self.voice_profiles.get_by_provider_voice_id(payload.provider, payload.voice_id)
        if existing:
            raise AppError("VOICE_PROFILE_ALREADY_EXISTS", "Voice profile already exists", 409)

        profile = VoiceProfile(
            id=str(uuid7()),
            display_name=payload.display_name,
            description=payload.description,
            provider=payload.provider,
            voice_id=payload.voice_id,
            profile_type=payload.profile_type,
            language=payload.language,
            gender=payload.gender,
            reference_audio_artifact_id=payload.reference_audio_artifact_id,
            source_character_id=payload.source_character_id,
            source_speaker_label=payload.source_speaker_label,
            sample_duration_ms=payload.sample_duration_ms,
            quality_score=payload.quality_score,
            average_similarity_score=payload.average_similarity_score,
            is_shared=payload.is_shared,
            status=payload.status,
            metadata_json=payload.metadata_json,
        )
        self.voice_profiles.create_profile(profile)
        self.db.commit()
        self.db.refresh(profile)
        return VoiceProfileResponse.model_validate(profile)

    def create_profile_from_sample(self, project_id: str, character_id: str, current_user_id: str) -> VoiceProfile:
        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)

        character = self.characters.get_character(character_id)
        if not character or character.project_id != project_id:
            raise AppError("CHARACTER_NOT_FOUND", "Character not found", 404)

        matching_references = [
            artifact
            for artifact in self.artifacts.list_for_project(project_id)
            if artifact.artifact_type.value == "VOICE_REFERENCE_AUDIO"
            and str((artifact.metadata_json or {}).get("character_id") or "") == character_id
        ]
        matching_references.sort(
            key=lambda artifact: (
                float((artifact.metadata_json or {}).get("sample_quality_score") or 0),
                int(artifact.duration_ms or 0),
                artifact.created_at,
            ),
            reverse=True,
        )
        reference_artifact = matching_references[0] if matching_references else None
        if not reference_artifact:
            raise AppError("VOICE_REFERENCE_NOT_FOUND", "Voice reference audio not found for character", 409)

        reference_metadata = reference_artifact.metadata_json or {}
        reference_path = self.storage.absolute_path(reference_artifact.storage_path)
        reference_analysis = self._validate_reference_audio(reference_artifact, reference_path)
        sample_quality_score = reference_metadata.get("sample_quality_score")
        character_display_name = (character.display_name or "").strip()
        profile = VoiceProfile(
            id=str(uuid7()),
            display_name=f"{character.display_name} Clone",
            description=f"Cloned profile generated from {character.display_name}",
            provider=self.settings.voice_clone_provider,
            voice_id=f"clone-{uuid7()}",
            profile_type="cloned",
            language=project.target_language or "tr",
            gender=None,
            reference_audio_artifact_id=reference_artifact.id,
            source_character_id=character.id,
            source_speaker_label=str(reference_metadata.get("speaker_label") or "") or None,
            sample_duration_ms=reference_artifact.duration_ms,
            quality_score=float(sample_quality_score) if sample_quality_score is not None else None,
            is_shared=False,
            status="ready",
            metadata_json={
                "reference_audio_artifact_id": reference_artifact.id,
                "source_character_id": character.id,
                "character_display_name": character_display_name,
                "source_speaker_label": reference_metadata.get("speaker_label"),
                "reference_text": reference_metadata.get("prompt_text"),
                "reference_language": reference_metadata.get("reference_language") or reference_metadata.get("source_language") or project.source_language,
                "target_language": project.target_language,
                "reference_duration_ms": reference_artifact.duration_ms,
                "sample_quality_score": sample_quality_score,
                "reference_audio_analysis": reference_analysis,
                "clone_validation": {
                    "status": "passed",
                    "required_duration_ms": self.settings.voice_clone_required_duration_ms,
                    "min_speech_ratio": self.settings.voice_clone_min_speech_ratio,
                    "max_silence_ratio": self.settings.voice_clone_max_silence_ratio,
                    "min_snr_db": self.settings.voice_clone_min_snr_db,
                    "min_quality_score": self.settings.voice_clone_min_quality_score,
                },
                "normalized": bool(reference_metadata.get("normalized")),
                "silence_trimmed": bool(reference_metadata.get("silence_trimmed")),
                "warning": reference_metadata.get("warning"),
            },
        )
        self.voice_profiles.create_profile(profile)
        self.db.flush()

        self.events.publish_audit(
            project_id=project_id,
            actor_user_id=current_user_id,
            entity_type="voice_profile",
            entity_id=profile.id,
            event_type=EventType.VOICE_PROFILE_CREATED_FROM_SAMPLE.value,
            payload_json={"character_id": character.id, "reference_audio_artifact_id": reference_artifact.id},
        )

        self._upsert_assignment(project_id, character.id, profile, current_user_id, assignment_source="manual")
        self.db.commit()
        return profile

    def _validate_reference_audio(self, reference_artifact, reference_path) -> dict:
        if not reference_path.exists():
            raise AppError("VOICE_REFERENCE_FILE_NOT_FOUND", "Voice reference file not found", 404)
        analysis = self.voice_similarity.analyze(reference_path)
        duration_ms = int(reference_artifact.duration_ms or (analysis["duration_seconds"] * 1000))
        quality_score = float((reference_artifact.metadata_json or {}).get("sample_quality_score") or 0)
        failures: list[str] = []
        if duration_ms < self.settings.voice_clone_required_duration_ms:
            failures.append("duration")
        if float(analysis["speech_ratio"]) < self.settings.voice_clone_min_speech_ratio:
            failures.append("speech_ratio")
        if float(analysis["silence_ratio"]) > self.settings.voice_clone_max_silence_ratio:
            failures.append("silence_ratio")
        if float(analysis["snr_estimate"]) < self.settings.voice_clone_min_snr_db:
            failures.append("snr")
        if quality_score < self.settings.voice_clone_min_quality_score:
            failures.append("quality_score")
        if failures:
            raise AppError(
                "VOICE_REFERENCE_QUALITY_TOO_LOW",
                (
                    "Voice sample too short or too noisy. Please upload at least 20 seconds "
                    "of clean speech with limited silence."
                ),
                409,
            )
        return analysis

    def update_profile(
        self,
        voice_profile_id: str,
        payload: VoiceProfileUpdateRequest,
        current_user_id: str | None = None,
    ) -> VoiceProfileResponse:
        del current_user_id
        profile = self.voice_profiles.get_profile(voice_profile_id)
        if not profile:
            raise AppError("VOICE_PROFILE_NOT_FOUND", "Voice profile not found", 404)

        if payload.display_name is not None:
            profile.display_name = payload.display_name
        if "description" in payload.model_fields_set:
            profile.description = payload.description
        if payload.profile_type is not None:
            profile.profile_type = payload.profile_type
        if payload.language is not None:
            profile.language = payload.language
        if "gender" in payload.model_fields_set:
            profile.gender = payload.gender
        if "reference_audio_artifact_id" in payload.model_fields_set:
            profile.reference_audio_artifact_id = payload.reference_audio_artifact_id
        if "source_character_id" in payload.model_fields_set:
            profile.source_character_id = payload.source_character_id
        if "source_speaker_label" in payload.model_fields_set:
            profile.source_speaker_label = payload.source_speaker_label
        if "sample_duration_ms" in payload.model_fields_set:
            profile.sample_duration_ms = payload.sample_duration_ms
        if "quality_score" in payload.model_fields_set:
            profile.quality_score = payload.quality_score
        if "average_similarity_score" in payload.model_fields_set:
            profile.average_similarity_score = payload.average_similarity_score
        if payload.is_shared is not None:
            profile.is_shared = payload.is_shared
        if payload.status is not None:
            profile.status = payload.status
        if payload.metadata_json is not None:
            profile.metadata_json = payload.metadata_json
        profile.updated_at = datetime.now(UTC)

        self.db.commit()
        self.db.refresh(profile)
        return VoiceProfileResponse.model_validate(profile)

    def assign_to_character(
        self,
        project_id: str,
        character_id: str,
        payload: CharacterVoiceAssignmentRequest,
        current_user_id: str,
    ) -> None:
        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)

        character = self.characters.get_character(character_id)
        if not character or character.project_id != project_id:
            raise AppError("CHARACTER_NOT_FOUND", "Character not found", 404)

        profile = self.voice_profiles.get_profile(payload.voice_profile_id)
        if not profile:
            raise AppError("VOICE_PROFILE_NOT_FOUND", "Voice profile not found", 404)

        self._upsert_assignment(project_id, character_id, profile, current_user_id, assignment_source="manual")
        self.db.commit()

    def resolve_voice_for_character(
        self,
        *,
        project_id: str,
        character_id: str | None,
        provider: str,
        language: str,
    ) -> tuple[VoiceProfile | None, str | None, str]:
        if character_id:
            assignment = self.voice_profiles.get_assignment(project_id, character_id)
            if assignment and assignment.voice_profile:
                return assignment.voice_profile, assignment.voice_profile.voice_id, "character_assignment"

        shared_default = self.voice_profiles.get_default_for_language(provider, language)
        if shared_default:
            return shared_default, shared_default.voice_id, "provider_default"

        shared_language_default = self.voice_profiles.get_shared_for_language(language)
        if shared_language_default:
            return shared_language_default, shared_language_default.voice_id, "shared_language_default"

        return None, None, "settings_fallback"

    def _upsert_assignment(
        self,
        project_id: str,
        character_id: str,
        profile: VoiceProfile,
        current_user_id: str,
        *,
        assignment_source: str,
    ) -> None:
        assignment = self.voice_profiles.get_assignment(project_id, character_id)
        if assignment:
            assignment.voice_profile_id = profile.id
            assignment.assignment_source = assignment_source
            assignment.updated_at = datetime.now(UTC)
        else:
            self.voice_profiles.create_assignment(
                CharacterVoiceAssignment(
                    id=str(uuid7()),
                    project_id=project_id,
                    character_id=character_id,
                    voice_profile_id=profile.id,
                    assignment_source=assignment_source,
                )
            )

        self.events.publish_audit(
            project_id=project_id,
            actor_user_id=current_user_id,
            entity_type="character",
            entity_id=character_id,
            event_type=EventType.VOICE_PROFILE_ASSIGNED_TO_CHARACTER.value,
            payload_json={"voice_profile_id": profile.id, "voice_id": profile.voice_id},
        )
