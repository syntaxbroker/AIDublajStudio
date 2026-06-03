from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.timeline_clip import TimelineClip
from app.models.translation_segment import TranslationSegment


class TranslationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, segment: TranslationSegment) -> TranslationSegment:
        self.db.add(segment)
        return segment

    def list_for_project(self, project_id: str) -> list[TranslationSegment]:
        stmt = select(TranslationSegment).where(TranslationSegment.project_id == project_id).order_by(TranslationSegment.created_at.asc())
        return list(self.db.scalars(stmt))

    def delete_for_project(self, project_id: str) -> None:
        self.db.execute(delete(TranslationSegment).where(TranslationSegment.project_id == project_id))

    def list_timeline_clips_for_project(self, project_id: str) -> list[TimelineClip]:
        stmt = select(TimelineClip).where(TimelineClip.project_id == project_id).order_by(TimelineClip.start_ms.asc())
        return list(self.db.scalars(stmt))
