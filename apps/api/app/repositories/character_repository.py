from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.character import Character, CharacterAssignment
from app.models.timeline_clip import TimelineClip


class CharacterRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_character(self, character: Character) -> Character:
        self.db.add(character)
        return character

    def create_assignment(self, assignment: CharacterAssignment) -> CharacterAssignment:
        self.db.add(assignment)
        return assignment

    def get_character(self, character_id: str) -> Character | None:
        return self.db.get(Character, character_id)

    def list_characters_for_project(self, project_id: str) -> list[Character]:
        stmt = select(Character).where(Character.project_id == project_id).order_by(Character.created_at.asc())
        return list(self.db.scalars(stmt))

    def list_assignments_for_project(self, project_id: str) -> list[CharacterAssignment]:
        stmt = select(CharacterAssignment).where(CharacterAssignment.project_id == project_id).order_by(CharacterAssignment.created_at.asc())
        return list(self.db.scalars(stmt))

    def get_speaker_mapping(self, project_id: str, speaker_label: str) -> CharacterAssignment | None:
        stmt = select(CharacterAssignment).where(
            CharacterAssignment.project_id == project_id,
            CharacterAssignment.speaker_label == speaker_label,
            CharacterAssignment.transcript_segment_id.is_(None),
            CharacterAssignment.timeline_clip_id.is_(None),
        )
        return self.db.scalar(stmt)

    def get_timeline_assignment(self, project_id: str, timeline_clip_id: str) -> CharacterAssignment | None:
        stmt = select(CharacterAssignment).where(
            CharacterAssignment.project_id == project_id,
            CharacterAssignment.timeline_clip_id == timeline_clip_id,
        )
        return self.db.scalar(stmt)

    def list_timeline_clips_for_project(self, project_id: str) -> list[TimelineClip]:
        stmt = select(TimelineClip).where(TimelineClip.project_id == project_id).order_by(TimelineClip.start_ms.asc())
        return list(self.db.scalars(stmt))

    def delete_auto_timeline_assignments(self, project_id: str) -> None:
        self.db.execute(
            delete(CharacterAssignment).where(
                CharacterAssignment.project_id == project_id,
                CharacterAssignment.assignment_source == "auto_from_speaker",
                CharacterAssignment.timeline_clip_id.is_not(None),
            )
        )
