from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.artifact import ArtifactResponse


class ArtifactService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.artifacts = ArtifactRepository(db)
        self.projects = ProjectRepository(db)

    def list_for_project(self, project_id: str, user_id: str) -> list[ArtifactResponse]:
        self._ensure_access(project_id, user_id)
        return [ArtifactResponse.model_validate(item) for item in self.artifacts.list_for_project(project_id)]

    def get_detail(self, project_id: str, artifact_id: str, user_id: str) -> ArtifactResponse:
        self._ensure_access(project_id, user_id)
        artifact = self.artifacts.get_by_id(artifact_id)
        if not artifact or artifact.project_id != project_id:
            raise AppError("ARTIFACT_NOT_FOUND", "Artifact not found", 404)
        return ArtifactResponse.model_validate(artifact)

    def _ensure_access(self, project_id: str, user_id: str) -> None:
        if not self.projects.user_has_access(project_id, user_id):
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
