from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.models.voice_profile import CharacterVoiceAssignment, VoiceProfile


class VoiceProfileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_profiles(self) -> list[VoiceProfile]:
        stmt = select(VoiceProfile).order_by(VoiceProfile.is_shared.desc(), VoiceProfile.display_name.asc())
        return list(self.db.scalars(stmt))

    def get_profile(self, voice_profile_id: str) -> VoiceProfile | None:
        return self.db.get(VoiceProfile, voice_profile_id)

    def get_latest_cloned_for_character(self, project_id: str, character_id: str) -> VoiceProfile | None:
        stmt = (
            select(VoiceProfile)
            .join(
                CharacterVoiceAssignment,
                CharacterVoiceAssignment.voice_profile_id == VoiceProfile.id,
            )
            .where(
                CharacterVoiceAssignment.project_id == project_id,
                CharacterVoiceAssignment.character_id == character_id,
                VoiceProfile.profile_type == "cloned",
            )
            .order_by(VoiceProfile.created_at.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def get_by_provider_voice_id(self, provider: str, voice_id: str) -> VoiceProfile | None:
        stmt = select(VoiceProfile).where(VoiceProfile.provider == provider, VoiceProfile.voice_id == voice_id)
        return self.db.scalar(stmt)

    def get_default_for_language(self, provider: str, language: str) -> VoiceProfile | None:
        stmt = (
            select(VoiceProfile)
            .where(
                VoiceProfile.provider == provider,
                VoiceProfile.language == language,
                VoiceProfile.is_shared.is_(True),
            )
            .order_by(
                case((VoiceProfile.gender == "male", 0), else_=1),
                VoiceProfile.created_at.asc(),
            )
            .limit(1)
        )
        return self.db.scalar(stmt)

    def get_shared_for_language(self, language: str) -> VoiceProfile | None:
        stmt = (
            select(VoiceProfile)
            .where(
                VoiceProfile.language == language,
                VoiceProfile.is_shared.is_(True),
            )
            .order_by(
                case((VoiceProfile.gender == "male", 0), else_=1),
                VoiceProfile.created_at.asc(),
            )
            .limit(1)
        )
        return self.db.scalar(stmt)

    def create_profile(self, voice_profile: VoiceProfile) -> VoiceProfile:
        self.db.add(voice_profile)
        return voice_profile

    def create_assignment(self, assignment: CharacterVoiceAssignment) -> CharacterVoiceAssignment:
        self.db.add(assignment)
        return assignment

    def get_assignment(self, project_id: str, character_id: str) -> CharacterVoiceAssignment | None:
        stmt = select(CharacterVoiceAssignment).where(
            CharacterVoiceAssignment.project_id == project_id,
            CharacterVoiceAssignment.character_id == character_id,
        )
        return self.db.scalar(stmt)

    def list_assignments_for_project(self, project_id: str) -> list[CharacterVoiceAssignment]:
        stmt = select(CharacterVoiceAssignment).where(CharacterVoiceAssignment.project_id == project_id)
        return list(self.db.scalars(stmt))
