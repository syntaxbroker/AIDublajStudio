from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.db.session import get_db
from app.schemas.voice_profile import VoiceProfileCreateRequest, VoiceProfileResponse, VoiceProfileUpdateRequest
from app.services.voice_profile_service import VoiceProfileService


router = APIRouter()


@router.get("", response_model=list[VoiceProfileResponse], responses=COMMON_ERROR_RESPONSES)
def list_voice_profiles(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[VoiceProfileResponse]:
    del current_user
    return VoiceProfileService(db).list_profiles()


@router.post("", response_model=VoiceProfileResponse, responses=COMMON_ERROR_RESPONSES)
def create_voice_profile(
    payload: VoiceProfileCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> VoiceProfileResponse:
    return VoiceProfileService(db).create_profile(payload, current_user.id)


@router.patch("/{voice_profile_id}", response_model=VoiceProfileResponse, responses=COMMON_ERROR_RESPONSES)
def update_voice_profile(
    voice_profile_id: str,
    payload: VoiceProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> VoiceProfileResponse:
    return VoiceProfileService(db).update_profile(voice_profile_id, payload, current_user.id)
