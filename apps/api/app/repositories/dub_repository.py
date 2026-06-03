from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.dub_segment import DubSegment


class DubRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, segment: DubSegment) -> DubSegment:
        self.db.add(segment)
        return segment

    def list_for_project(self, project_id: str) -> list[DubSegment]:
        stmt = select(DubSegment).where(DubSegment.project_id == project_id).order_by(DubSegment.created_at.asc())
        return list(self.db.scalars(stmt))

    def delete_for_project(self, project_id: str) -> None:
        self.db.execute(delete(DubSegment).where(DubSegment.project_id == project_id))
