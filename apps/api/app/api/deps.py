from collections.abc import Generator

from fastapi import Depends, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.repositories.user_repository import UserRepository
from app.services.provider_status_service import ProviderStatusService


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise AppError("INVALID_TOKEN", "Invalid token", 401)

    user = UserRepository(db).get_by_id(user_id)
    if not user or not user.is_active:
        raise AppError("USER_NOT_FOUND", "User not found", 401)
    return user


def enforce_ui_provider_safety(x_aidublaj_client: str | None = Header(default=None, alias="X-AIDublaj-Client")) -> None:
    if x_aidublaj_client == "web":
        ProviderStatusService().enforce_real_processing_allowed()


def require_admin(user=Depends(get_current_user)):
    if user.role != "ADMIN":
        raise AppError("ADMIN_ACCESS_REQUIRED", "Admin access required", 403)
    return user
