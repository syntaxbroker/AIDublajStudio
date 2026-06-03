from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import EventType
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.character import Character, CharacterAssignment
from app.repositories.character_repository import CharacterRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.character import CharacterRenameRequest
from app.services.event_service import EventService


class CharacterService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.projects = ProjectRepository(db)
        self.characters = CharacterRepository(db)
        self.events = EventService(db)

    def create_from_speakers(self, project_id: str, current_user_id: str) -> None:
        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)

        unique_speakers = sorted({clip.speaker_label for clip in project.timeline_clips if clip.speaker_label})
        if not unique_speakers:
            raise AppError("SPEAKER_LABELS_NOT_FOUND", "Speaker labels are required before character generation", 409)

        self.characters.delete_auto_timeline_assignments(project_id)

        ordered_characters = self.characters.list_characters_for_project(project_id)
        next_number = len(ordered_characters) + 1
        speaker_to_character: dict[str, Character] = {}

        for speaker_label in unique_speakers:
            mapping = self.characters.get_speaker_mapping(project_id, speaker_label)
            if mapping:
                character = self.characters.get_character(mapping.character_id)
                if character:
                    speaker_to_character[speaker_label] = character
                    continue

            character = Character(
                id=str(uuid7()),
                project_id=project_id,
                display_name=f"Character {next_number}",
                description=f"Generated from {speaker_label}",
                source_type="speaker",
            )
            next_number += 1
            self.characters.create_character(character)
            speaker_to_character[speaker_label] = character
            self.events.publish_audit(
                project_id=project_id,
                actor_user_id=current_user_id,
                entity_type="character",
                entity_id=character.id,
                event_type=EventType.CHARACTER_CREATED.value,
                payload_json={"speaker_label": speaker_label, "display_name": character.display_name},
            )
            self.characters.create_assignment(
                CharacterAssignment(
                    id=str(uuid7()),
                    project_id=project_id,
                    character_id=character.id,
                    speaker_label=speaker_label,
                    confidence=1.0,
                    assignment_source="auto_from_speaker",
                )
            )

        for clip in self.characters.list_timeline_clips_for_project(project_id):
            if not clip.speaker_label:
                continue
            character = speaker_to_character.get(clip.speaker_label)
            if not character:
                continue
            clip.character_id = character.id
            clip.updated_at = datetime.now(UTC)
            metadata = dict(clip.metadata_json or {})
            metadata["character_id"] = character.id
            metadata["character_display_name"] = character.display_name
            clip.metadata_json = metadata

            existing_assignment = self.characters.get_timeline_assignment(project_id, clip.id)
            if existing_assignment:
                existing_assignment.character_id = character.id
                existing_assignment.speaker_label = clip.speaker_label
                existing_assignment.confidence = 1.0
                existing_assignment.updated_at = datetime.now(UTC)
            else:
                self.characters.create_assignment(
                    CharacterAssignment(
                        id=str(uuid7()),
                        project_id=project_id,
                        character_id=character.id,
                        speaker_label=clip.speaker_label,
                        timeline_clip_id=clip.id,
                        confidence=1.0,
                        assignment_source="auto_from_speaker",
                    )
                )
            self.events.publish_audit(
                project_id=project_id,
                actor_user_id=current_user_id,
                entity_type="timeline_clip",
                entity_id=clip.id,
                event_type=EventType.CHARACTER_ASSIGNED_TO_TIMELINE.value,
                payload_json={"character_id": character.id, "speaker_label": clip.speaker_label},
            )

        self.db.commit()

    def rename_character(self, project_id: str, character_id: str, payload: CharacterRenameRequest, current_user_id: str) -> None:
        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
        try:
            UUID(character_id)
        except ValueError as exc:
            raise AppError("CHARACTER_NOT_FOUND", "Character not found", 404) from exc
        character = self.characters.get_character(character_id)
        if not character or character.project_id != project_id:
            raise AppError("CHARACTER_NOT_FOUND", "Character not found", 404)

        character.display_name = payload.display_name
        character.description = payload.description
        character.updated_at = datetime.now(UTC)

        for clip in self.characters.list_timeline_clips_for_project(project_id):
            if clip.character_id != character.id:
                continue
            metadata = dict(clip.metadata_json or {})
            metadata["character_display_name"] = character.display_name
            clip.metadata_json = metadata
            clip.updated_at = datetime.now(UTC)

        self.events.publish_audit(
            project_id=project_id,
            actor_user_id=current_user_id,
            entity_type="character",
            entity_id=character.id,
            event_type=EventType.CHARACTER_RENAMED.value,
            payload_json={"display_name": character.display_name},
        )
        self.db.commit()
