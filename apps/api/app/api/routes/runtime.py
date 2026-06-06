from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.enums import ArtifactType
from app.core.errors import AppError
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.db.session import get_db
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.timeline_repository import TimelineRepository
from app.schemas.runtime import ProjectDurationItem, ProjectDurationReportResponse, ProviderStatusResponse
from app.services.provider_status_service import ProviderStatusService


router = APIRouter()


@router.get("/runtime/providers", response_model=ProviderStatusResponse, responses=COMMON_ERROR_RESPONSES)
def provider_status() -> ProviderStatusResponse:
    return ProviderStatusService().status()


@router.get(
    "/projects/{project_id}/diagnostics/durations",
    response_model=ProjectDurationReportResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def project_duration_report(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProjectDurationReportResponse:
    projects = ProjectRepository(db)
    if not projects.user_has_access(project_id, current_user.id):
        raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)

    artifact_types = {
        ArtifactType.SOURCE_VIDEO,
        ArtifactType.PROXY_VIDEO,
        ArtifactType.FINAL_DUB_AUDIO,
        ArtifactType.LIPSYNC_VIDEO,
        ArtifactType.FINAL_RENDER,
    }
    artifacts = [
        ProjectDurationItem(
            artifact_id=artifact.id,
            artifact_type=artifact.artifact_type.value,
            duration_ms=artifact.duration_ms,
            storage_path=artifact.storage_path,
        )
        for artifact in ArtifactRepository(db).list_for_project(project_id)
        if artifact.artifact_type in artifact_types
    ]
    timeline_ends = [clip.end_ms for clip in TimelineRepository(db).list_clips_for_project(project_id)]
    return ProjectDurationReportResponse(
        project_id=project_id,
        max_timeline_end_ms=max(timeline_ends) if timeline_ends else None,
        active_providers=ProviderStatusService().status(),
        artifacts=artifacts,
    )
