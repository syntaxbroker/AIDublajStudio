from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.db.session import get_db
from app.schemas.project import ProjectDetailResponse
from app.services.upload_service import UploadService


router = APIRouter()


@router.post("/{project_id}/upload", response_model=ProjectDetailResponse, responses=COMMON_ERROR_RESPONSES)
def upload_source_video(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDetailResponse:
    return UploadService(db).upload_source_video(project_id, file, current_user)
