from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.timeline_clip import TimelineClip
from app.models.transcript_segment import TranscriptSegment


class TranscriptRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        self.db.add(segment)
        return segment

    def create_clip(self, clip: TimelineClip) -> TimelineClip:
        self.db.add(clip)
        return clip

    def list_segments_for_project(self, project_id: str) -> list[TranscriptSegment]:
        stmt = select(TranscriptSegment).where(TranscriptSegment.project_id == project_id).order_by(TranscriptSegment.start_ms.asc())
        return list(self.db.scalars(stmt))

    def list_clips_for_project(self, project_id: str) -> list[TimelineClip]:
        stmt = select(TimelineClip).where(TimelineClip.project_id == project_id).order_by(TimelineClip.start_ms.asc())
        return list(self.db.scalars(stmt))

    def delete_segments_for_project(self, project_id: str) -> None:
        self.db.execute(delete(TranscriptSegment).where(TranscriptSegment.project_id == project_id))

    def delete_clips_for_project(self, project_id: str) -> None:
        self.db.execute(delete(TimelineClip).where(TimelineClip.project_id == project_id))
