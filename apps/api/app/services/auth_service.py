from sqlalchemy.orm import Session

from app.core.enums import EventType
from app.core.errors import AppError
from app.core.security import create_access_token, verify_password
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse
from app.services.event_service import EventService


class AuthService:
    def __init__(self, db: Session) -> None:
        self.users = UserRepository(db)
        self.events = EventService(db)

    def login(self, email: str, password: str) -> TokenResponse:
        user = self.users.get_by_email(email)
        if not user or not verify_password(password, user.password_hash):
            raise AppError("INVALID_CREDENTIALS", "Invalid credentials", 401)
        self.events.publish_audit(
            event_type=EventType.USER_LOGIN.value,
            entity_type="user",
            actor_user_id=user.id,
            entity_id=user.id,
            payload_json={"email": user.email},
        )
        return TokenResponse(access_token=create_access_token(user.id))
