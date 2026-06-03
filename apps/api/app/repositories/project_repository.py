from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectMember


class ProjectRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, project: Project) -> Project:
        self.db.add(project)
        return project

    def add_member(self, member: ProjectMember) -> ProjectMember:
        self.db.add(member)
        return member

    def get_by_id(self, project_id: str) -> Project | None:
        return self.db.get(Project, project_id)

    def list_for_user(self, user_id: str) -> list[Project]:
        stmt = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        return list(self.db.scalars(stmt))

    def user_has_access(self, project_id: str, user_id: str) -> bool:
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        return self.db.scalar(stmt) is not None
