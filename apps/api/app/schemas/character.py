from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.voice_profile import VoiceProfileResponse


class CharacterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    display_name: str
    description: str | None
    source_type: str
    assigned_voice_profile_id: str | None = None
    assigned_voice_profile: VoiceProfileResponse | None = None
    created_at: datetime
    updated_at: datetime


class CharacterAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    character_id: str
    speaker_label: str | None
    transcript_segment_id: str | None
    timeline_clip_id: str | None
    confidence: float | None
    assignment_source: str
    created_at: datetime
    updated_at: datetime


class CharacterRenameRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
