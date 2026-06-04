from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.security import hash_password
from app.core.uuid7 import uuid7
from app.db.session import SessionLocal
from app.models.user import User
from app.models.voice_profile import VoiceProfile
from app.repositories.user_repository import UserRepository
from app.repositories.voice_profile_repository import VoiceProfileRepository


class BootstrapService:
    def ensure_default_users(self) -> None:
        settings = get_settings()
        with SessionLocal() as db:
            repo = UserRepository(db)
            users = [
                {
                    "email": settings.default_admin_email,
                    "password": settings.default_admin_password,
                    "full_name": "Default Admin",
                    "role": "ADMIN",
                },
                {
                    "email": settings.default_editor_email,
                    "password": settings.default_editor_password,
                    "full_name": "Default Editor",
                    "role": "EDITOR",
                },
            ]
            for item in users:
                existing = repo.get_by_email(item["email"])
                if existing:
                    existing.password_hash = hash_password(item["password"])
                    existing.full_name = item["full_name"]
                    existing.role = item["role"]
                    existing.is_active = True
                    repo.save(existing)
                    continue

                repo.create(
                    User(
                        id=str(uuid7()),
                        email=item["email"],
                        password_hash=hash_password(item["password"]),
                        full_name=item["full_name"],
                        role=item["role"],
                    )
                )
            db.commit()

    def ensure_default_voice_profiles(self) -> None:
        default_profiles = [
            {
                "display_name": "Ahmet (Edge TR)",
                "description": "Default Turkish male voice",
                "provider": "edge_tts",
                "voice_id": "tr-TR-AhmetNeural",
                "profile_type": "edge_tts",
                "language": "tr",
                "gender": "male",
                "quality_score": 88.0,
                "is_shared": True,
                "status": "ready",
                "metadata_json": {"is_default": True},
            },
            {
                "display_name": "Emel (Edge TR)",
                "description": "Default Turkish female voice",
                "provider": "edge_tts",
                "voice_id": "tr-TR-EmelNeural",
                "profile_type": "edge_tts",
                "language": "tr",
                "gender": "female",
                "quality_score": 88.0,
                "is_shared": True,
                "status": "ready",
                "metadata_json": {"is_default": True},
            },
        ]

        with SessionLocal() as db:
            repo = VoiceProfileRepository(db)
            for item in default_profiles:
                existing = repo.get_by_provider_voice_id(item["provider"], item["voice_id"])
                if existing:
                    existing.display_name = item["display_name"]
                    existing.description = item["description"]
                    existing.language = item["language"]
                    existing.gender = item["gender"]
                    existing.profile_type = item["profile_type"]
                    existing.quality_score = item["quality_score"]
                    existing.is_shared = item["is_shared"]
                    existing.status = item["status"]
                    existing.metadata_json = item["metadata_json"]
                    existing.updated_at = datetime.now(UTC)
                    continue

                repo.create_profile(
                    VoiceProfile(
                        id=str(uuid7()),
                        display_name=item["display_name"],
                        description=item["description"],
                        provider=item["provider"],
                        voice_id=item["voice_id"],
                        profile_type=item["profile_type"],
                        language=item["language"],
                        gender=item["gender"],
                        quality_score=item["quality_score"],
                        is_shared=item["is_shared"],
                        status=item["status"],
                        metadata_json=item["metadata_json"],
                    )
                )
            db.commit()
