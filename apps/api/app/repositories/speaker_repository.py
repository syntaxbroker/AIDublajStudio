from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.speaker_segment import SpeakerSegment
from app.models.timeline_clip import TimelineClip
from app.models.transcript_segment import TranscriptSegment


class SpeakerRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, segment: SpeakerSegment) -> SpeakerSegment:
        self.db.add(segment)
        return segment

    def list_for_project(self, project_id: str) -> list[SpeakerSegment]:
        stmt = select(SpeakerSegment).where(SpeakerSegment.project_id == project_id).order_by(SpeakerSegment.start_ms.asc())
        return list(self.db.scalars(stmt))

    def delete_for_project(self, project_id: str) -> None:
        self.db.execute(delete(SpeakerSegment).where(SpeakerSegment.project_id == project_id))

    def list_transcript_segments_for_project(self, project_id: str) -> list[TranscriptSegment]:
        stmt = select(TranscriptSegment).where(TranscriptSegment.project_id == project_id).order_by(TranscriptSegment.start_ms.asc())
        return list(self.db.scalars(stmt))

    def list_timeline_clips_for_project(self, project_id: str) -> list[TimelineClip]:
        stmt = select(TimelineClip).where(TimelineClip.project_id == project_id).order_by(TimelineClip.start_ms.asc())
        return list(self.db.scalars(stmt))
