from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.core.uuid7 import uuid7
from app.db.session import SessionLocal
from app.models.user import User
from app.repositories.user_repository import UserRepository


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
