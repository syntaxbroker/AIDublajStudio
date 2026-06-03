from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.character import Character, CharacterAssignment
from app.models.timeline_clip import TimelineClip


class TimelineRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_clip(self, clip_id: str) -> TimelineClip | None:
        return self.db.get(TimelineClip, clip_id)

    def list_clips_for_project(self, project_id: str) -> list[TimelineClip]:
        stmt = select(TimelineClip).where(TimelineClip.project_id == project_id).order_by(TimelineClip.start_ms.asc(), TimelineClip.created_at.asc())
        return list(self.db.scalars(stmt))

    def list_other_clips_for_overlap(
        self,
        project_id: str,
        *,
        lane: str,
        track_index: int,
        exclude_clip_ids: set[str] | None = None,
    ) -> list[TimelineClip]:
        stmt = select(TimelineClip).where(
            TimelineClip.project_id == project_id,
            TimelineClip.lane == lane,
            TimelineClip.track_index == track_index,
        )
        clips = list(self.db.scalars(stmt))
        if not exclude_clip_ids:
            return clips
        return [clip for clip in clips if clip.id not in exclude_clip_ids]

    def create_clip(self, clip: TimelineClip) -> TimelineClip:
        self.db.add(clip)
        return clip

    def delete_clip(self, clip: TimelineClip) -> None:
        self.db.delete(clip)

    def get_character(self, character_id: str) -> Character | None:
        return self.db.get(Character, character_id)

    def get_timeline_assignment(self, project_id: str, timeline_clip_id: str) -> CharacterAssignment | None:
        stmt = select(CharacterAssignment).where(
            CharacterAssignment.project_id == project_id,
            CharacterAssignment.timeline_clip_id == timeline_clip_id,
        )
        return self.db.scalar(stmt)

    def create_assignment(self, assignment: CharacterAssignment) -> CharacterAssignment:
        self.db.add(assignment)
        return assignment

    def delete_timeline_assignments(self, project_id: str, timeline_clip_ids: list[str]) -> None:
        if not timeline_clip_ids:
            return
        self.db.execute(
            delete(CharacterAssignment).where(
                CharacterAssignment.project_id == project_id,
                CharacterAssignment.timeline_clip_id.in_(timeline_clip_ids),
            )
        )
