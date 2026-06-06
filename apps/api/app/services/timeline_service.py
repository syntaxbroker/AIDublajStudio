from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import EventType
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.character import CharacterAssignment
from app.models.timeline_clip import TimelineClip
from app.repositories.project_repository import ProjectRepository
from app.repositories.timeline_repository import TimelineRepository
from app.services.translation_adaptation import build_adaptation_metadata
from app.schemas.timeline import (
    TimelineClipMergeRequest,
    TimelineClipResponse,
    TimelineClipSplitRequest,
    TimelineClipUpdateRequest,
    TimelineResponse,
)
from app.services.event_service import EventService


class TimelineService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.projects = ProjectRepository(db)
        self.timeline = TimelineRepository(db)
        self.events = EventService(db)

    def get_timeline(self, project_id: str) -> TimelineResponse:
        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
        clips = self.timeline.list_clips_for_project(project_id)
        return TimelineResponse(
            project_id=project_id,
            clips=[TimelineClipResponse.model_validate(clip) for clip in clips],
        )

    def update_clip(
        self,
        project_id: str,
        clip_id: str,
        payload: TimelineClipUpdateRequest,
        current_user_id: str,
    ) -> TimelineResponse:
        clip = self._get_project_clip(project_id, clip_id)
        new_start_ms = payload.start_ms if "start_ms" in payload.model_fields_set else clip.start_ms
        new_end_ms = payload.end_ms if "end_ms" in payload.model_fields_set else clip.end_ms
        self._validate_range(new_start_ms, new_end_ms)
        self._validate_overlap(project_id, clip, new_start_ms, new_end_ms, exclude_clip_ids={clip.id})

        if "character_id" in payload.model_fields_set:
            character = self._resolve_character(project_id, payload.character_id)
            clip.character_id = character.id if character else None

        if "speaker_label" in payload.model_fields_set:
            clip.speaker_label = payload.speaker_label
        if "text" in payload.model_fields_set:
            clip.text = payload.text
        if "translation_text" in payload.model_fields_set:
            clip.translation_text = payload.translation_text

        clip.start_ms = new_start_ms
        clip.end_ms = new_end_ms
        self._mark_edited(clip, current_user_id)
        self._sync_clip_metadata(clip)
        self._sync_character_assignment(clip, current_user_id)

        self.events.publish_audit(
            project_id=project_id,
            actor_user_id=current_user_id,
            entity_type="timeline_clip",
            entity_id=clip.id,
            event_type=EventType.TIMELINE_CLIP_UPDATED.value,
            payload_json={
                "start_ms": clip.start_ms,
                "end_ms": clip.end_ms,
                "text": clip.text,
                "translation_text": clip.translation_text,
                "character_id": clip.character_id,
                "speaker_label": clip.speaker_label,
                "edit_version": clip.edit_version,
            },
        )
        self.db.commit()
        return self.get_timeline(project_id)

    def split_clip(
        self,
        project_id: str,
        clip_id: str,
        payload: TimelineClipSplitRequest,
        current_user_id: str,
    ) -> TimelineResponse:
        clip = self._get_project_clip(project_id, clip_id)
        split_at_ms = payload.split_at_ms
        if split_at_ms <= clip.start_ms or split_at_ms >= clip.end_ms:
            raise AppError("TIMELINE_SPLIT_POINT_INVALID", "Split point must be inside clip range", 409)

        second_clip = TimelineClip(
            id=str(uuid7()),
            project_id=clip.project_id,
            project_version_id=clip.project_version_id,
            transcript_segment_id=clip.transcript_segment_id,
            translation_segment_id=clip.translation_segment_id,
            dub_segment_id=clip.dub_segment_id,
            artifact_id=clip.artifact_id,
            character_id=clip.character_id,
            edited_by_user_id=current_user_id,
            speaker_label=clip.speaker_label,
            text=clip.text,
            translation_text=clip.translation_text,
            clip_type=clip.clip_type,
            track_index=clip.track_index,
            start_ms=split_at_ms,
            end_ms=clip.end_ms,
            lane=clip.lane,
            is_locked=clip.is_locked,
            edit_version=clip.edit_version + 1,
            metadata_json=dict(clip.metadata_json or {}),
            edited_at=datetime.now(UTC),
        )

        clip.end_ms = split_at_ms
        self._mark_edited(clip, current_user_id)
        self._sync_clip_metadata(clip)
        self._sync_clip_metadata(second_clip)
        self._validate_overlap(project_id, clip, clip.start_ms, clip.end_ms, exclude_clip_ids={clip.id})
        self._validate_overlap(project_id, second_clip, second_clip.start_ms, second_clip.end_ms, exclude_clip_ids={clip.id, second_clip.id})
        self.timeline.create_clip(second_clip)
        self.db.flush()
        self._sync_character_assignment(clip, current_user_id)
        self._sync_character_assignment(second_clip, current_user_id)

        self.events.publish_audit(
            project_id=project_id,
            actor_user_id=current_user_id,
            entity_type="timeline_clip",
            entity_id=clip.id,
            event_type=EventType.TIMELINE_CLIP_SPLIT.value,
            payload_json={"original_clip_id": clip.id, "new_clip_id": second_clip.id, "split_at_ms": split_at_ms},
        )
        self.db.commit()
        return self.get_timeline(project_id)

    def merge_clips(
        self,
        project_id: str,
        payload: TimelineClipMergeRequest,
        current_user_id: str,
    ) -> TimelineResponse:
        unique_clip_ids = list(dict.fromkeys(payload.clip_ids))
        if len(unique_clip_ids) < 2:
            raise AppError("TIMELINE_MERGE_REQUIRES_MULTIPLE_CLIPS", "At least two clips are required for merge", 409)

        clips = [self._get_project_clip(project_id, clip_id) for clip_id in unique_clip_ids]
        ordered_clips = sorted(clips, key=lambda clip: (clip.start_ms, clip.created_at))
        base_clip = ordered_clips[0]

        lane = base_clip.lane
        track_index = base_clip.track_index
        if any(clip.lane != lane or clip.track_index != track_index for clip in ordered_clips):
            raise AppError("TIMELINE_MERGE_TRACK_MISMATCH", "Clips must be on the same track and lane", 409)

        for left, right in zip(ordered_clips, ordered_clips[1:], strict=False):
            if right.start_ms < left.end_ms:
                raise AppError("TIMELINE_MERGE_OVERLAP_INVALID", "Overlapping clips cannot be merged", 409)

        base_clip.start_ms = ordered_clips[0].start_ms
        base_clip.end_ms = ordered_clips[-1].end_ms
        base_clip.text = self._merge_text_values([clip.text for clip in ordered_clips])
        base_clip.translation_text = self._merge_text_values([clip.translation_text for clip in ordered_clips])
        base_clip.speaker_label = self._coalesce_single_value([clip.speaker_label for clip in ordered_clips])
        base_clip.character_id = self._coalesce_single_value([clip.character_id for clip in ordered_clips])
        base_clip.transcript_segment_id = self._coalesce_single_value([clip.transcript_segment_id for clip in ordered_clips])
        base_clip.translation_segment_id = self._coalesce_single_value([clip.translation_segment_id for clip in ordered_clips])
        self._mark_edited(base_clip, current_user_id)
        self._sync_clip_metadata(base_clip)
        self._validate_overlap(
            project_id,
            base_clip,
            base_clip.start_ms,
            base_clip.end_ms,
            exclude_clip_ids={clip.id for clip in ordered_clips},
        )

        removed_clip_ids = [clip.id for clip in ordered_clips[1:]]
        self.timeline.delete_timeline_assignments(project_id, removed_clip_ids)
        for clip in ordered_clips[1:]:
            self.timeline.delete_clip(clip)

        self.db.flush()
        self._sync_character_assignment(base_clip, current_user_id)

        self.events.publish_audit(
            project_id=project_id,
            actor_user_id=current_user_id,
            entity_type="timeline_clip",
            entity_id=base_clip.id,
            event_type=EventType.TIMELINE_CLIPS_MERGED.value,
            payload_json={"merged_clip_ids": unique_clip_ids, "result_clip_id": base_clip.id},
        )
        self.db.commit()
        return self.get_timeline(project_id)

    def _get_project_clip(self, project_id: str, clip_id: str) -> TimelineClip:
        clip = self.timeline.get_clip(clip_id)
        if not clip or clip.project_id != project_id:
            raise AppError("TIMELINE_CLIP_NOT_FOUND", "Timeline clip not found", 404)
        return clip

    def _validate_range(self, start_ms: int, end_ms: int) -> None:
        if start_ms >= end_ms:
            raise AppError("TIMELINE_CLIP_RANGE_INVALID", "Timeline clip range is invalid", 409)

    def _validate_overlap(
        self,
        project_id: str,
        reference_clip: TimelineClip,
        start_ms: int,
        end_ms: int,
        *,
        exclude_clip_ids: set[str],
    ) -> None:
        other_clips = self.timeline.list_other_clips_for_overlap(
            project_id,
            lane=reference_clip.lane,
            track_index=reference_clip.track_index,
            exclude_clip_ids=exclude_clip_ids,
        )
        for other in other_clips:
            if start_ms < other.end_ms and end_ms > other.start_ms:
                raise AppError("TIMELINE_CLIP_OVERLAP", "Timeline clip overlaps with an existing clip", 409)

    def _resolve_character(self, project_id: str, character_id: str | None):
        if character_id is None:
            return None
        try:
            UUID(character_id)
        except ValueError as exc:
            raise AppError("CHARACTER_NOT_FOUND", "Character not found", 404) from exc
        character = self.timeline.get_character(character_id)
        if not character or character.project_id != project_id:
            raise AppError("CHARACTER_NOT_FOUND", "Character not found", 404)
        return character

    def _mark_edited(self, clip: TimelineClip, current_user_id: str) -> None:
        now = datetime.now(UTC)
        clip.edited_by_user_id = current_user_id
        clip.edited_at = now
        clip.updated_at = now
        clip.edit_version = int(clip.edit_version or 0) + 1

    def _sync_clip_metadata(self, clip: TimelineClip) -> None:
        metadata = dict(clip.metadata_json or {})
        metadata["text"] = clip.text
        metadata["translated_text"] = clip.translation_text
        if clip.translation_text:
            metadata.update(build_adaptation_metadata(self._duration_ms(clip), clip.translation_text))
        metadata["speaker_label"] = clip.speaker_label
        metadata["character_id"] = clip.character_id
        clip.metadata_json = metadata

    def _sync_character_assignment(self, clip: TimelineClip, current_user_id: str) -> None:
        assignment = self.timeline.get_timeline_assignment(clip.project_id, clip.id)
        if not clip.character_id:
            if assignment:
                self.db.delete(assignment)
            return

        if assignment:
            assignment.character_id = clip.character_id
            assignment.speaker_label = clip.speaker_label
            assignment.confidence = 1.0
            assignment.assignment_source = "manual"
            assignment.updated_at = datetime.now(UTC)
            return

        self.timeline.create_assignment(
            CharacterAssignment(
                id=str(uuid7()),
                project_id=clip.project_id,
                character_id=clip.character_id,
                speaker_label=clip.speaker_label,
                timeline_clip_id=clip.id,
                confidence=1.0,
                assignment_source="manual",
            )
        )
        self.events.publish_audit(
            project_id=clip.project_id,
            actor_user_id=current_user_id,
            entity_type="timeline_clip",
            entity_id=clip.id,
            event_type=EventType.CHARACTER_ASSIGNED_TO_TIMELINE.value,
            payload_json={"character_id": clip.character_id, "speaker_label": clip.speaker_label},
        )

    def _duration_ms(self, clip: TimelineClip) -> int:
        return max(int(clip.end_ms or 0) - int(clip.start_ms or 0), 1)

    def _join_values(self, values: list[str | None]) -> str | None:
        cleaned = [value.strip() for value in values if value and value.strip()]
        if not cleaned:
            return None
        return " ".join(cleaned)

    def _merge_text_values(self, values: list[str | None]) -> str | None:
        cleaned = [value.strip() for value in values if value and value.strip()]
        if not cleaned:
            return None
        unique_values = list(dict.fromkeys(cleaned))
        if len(unique_values) == 1:
            return unique_values[0]
        return " ".join(cleaned)

    def _coalesce_single_value(self, values: list[str | None]) -> str | None:
        cleaned = [value for value in values if value]
        if not cleaned:
            return None
        unique_values = list(dict.fromkeys(cleaned))
        if len(unique_values) == 1:
            return unique_values[0]
        return None
