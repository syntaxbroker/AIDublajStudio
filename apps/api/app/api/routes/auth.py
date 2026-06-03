from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.db.session import get_db
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthService


router = APIRouter()


@router.post("/login", response_model=TokenResponse, responses=COMMON_ERROR_RESPONSES)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    return AuthService(db).login(payload.email, payload.password)


@router.get("/me", response_model=UserResponse, responses=COMMON_ERROR_RESPONSES)
def me(current_user=Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)
