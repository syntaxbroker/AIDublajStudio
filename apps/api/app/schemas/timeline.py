from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ClipType


class TimelineClipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    transcript_segment_id: str | None
    translation_segment_id: str | None
    dub_segment_id: str | None = None
    artifact_id: str | None
    character_id: str | None = None
    edited_by_user_id: str | None = None
    speaker_label: str | None = None
    text: str | None = None
    translation_text: str | None = None
    clip_type: ClipType
    track_index: int
    start_ms: int
    end_ms: int
    source_duration_ms: int
    translated_duration_ms: int | None = None
    duration_match_score: float | None = None
    lane: str
    is_locked: bool
    edit_version: int
    metadata_json: dict
    edited_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TimelineResponse(BaseModel):
    project_id: str
    clips: list[TimelineClipResponse] = Field(default_factory=list)


class TimelineClipUpdateRequest(BaseModel):
    start_ms: int | None = None
    end_ms: int | None = None
    text: str | None = None
    translation_text: str | None = None
    character_id: str | None = None
    speaker_label: str | None = None


class TimelineClipSplitRequest(BaseModel):
    split_at_ms: int


class TimelineClipMergeRequest(BaseModel):
    clip_ids: list[str] = Field(min_length=2)
