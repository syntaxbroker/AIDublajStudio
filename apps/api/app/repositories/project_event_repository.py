from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import ProjectEvent


class ProjectEventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, event: ProjectEvent) -> ProjectEvent:
        self.db.add(event)
        return event

    def list_for_project(self, project_id: str) -> list[ProjectEvent]:
        stmt = select(ProjectEvent).where(ProjectEvent.project_id == project_id).order_by(ProjectEvent.created_at.desc())
        return list(self.db.scalars(stmt))
