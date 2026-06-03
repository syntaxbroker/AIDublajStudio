from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user: User) -> User:
        self.db.add(user)
        return user

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return self.db.scalar(stmt)

    def get_by_id(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)

    def any_exists(self) -> bool:
        stmt = select(User.id).limit(1)
        return self.db.scalar(stmt) is not None

    def save(self, user: User) -> User:
        self.db.add(user)
        return user
