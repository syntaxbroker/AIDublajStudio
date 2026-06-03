from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.db.session import get_db
from app.schemas.artifact import ArtifactResponse
from app.services.artifact_service import ArtifactService


router = APIRouter()


@router.get("/{project_id}/artifacts", response_model=list[ArtifactResponse], responses=COMMON_ERROR_RESPONSES)
def list_artifacts(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[ArtifactResponse]:
    return ArtifactService(db).list_for_project(project_id, current_user.id)


@router.get("/{project_id}/artifacts/{artifact_id}", response_model=ArtifactResponse, responses=COMMON_ERROR_RESPONSES)
def get_artifact(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ArtifactResponse:
    return ArtifactService(db).get_detail(project_id, artifact_id, current_user.id)
