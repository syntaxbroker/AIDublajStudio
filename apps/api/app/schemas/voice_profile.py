from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VoiceProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    description: str | None
    provider: str
    voice_id: str
    profile_type: str
    language: str
    gender: str | None
    reference_audio_artifact_id: str | None
    source_character_id: str | None
    source_speaker_label: str | None
    sample_duration_ms: int | None
    quality_score: float | None
    average_similarity_score: float | None = None
    is_shared: bool
    status: str
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class VoiceProfileCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    provider: str = Field(min_length=1, max_length=64)
    voice_id: str = Field(min_length=1, max_length=255)
    profile_type: str = Field(default="imported", min_length=1, max_length=32)
    language: str = Field(min_length=2, max_length=16)
    gender: str | None = Field(default=None, max_length=32)
    reference_audio_artifact_id: str | None = None
    source_character_id: str | None = None
    source_speaker_label: str | None = Field(default=None, max_length=64)
    sample_duration_ms: int | None = None
    quality_score: float | None = None
    average_similarity_score: float | None = None
    is_shared: bool = True
    status: str = Field(default="ready", min_length=1, max_length=32)
    metadata_json: dict = Field(default_factory=dict)


class VoiceProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    profile_type: str | None = Field(default=None, min_length=1, max_length=32)
    language: str | None = Field(default=None, min_length=2, max_length=16)
    gender: str | None = Field(default=None, max_length=32)
    reference_audio_artifact_id: str | None = None
    source_character_id: str | None = None
    source_speaker_label: str | None = Field(default=None, max_length=64)
    sample_duration_ms: int | None = None
    quality_score: float | None = None
    average_similarity_score: float | None = None
    is_shared: bool | None = None
    status: str | None = Field(default=None, min_length=1, max_length=32)
    metadata_json: dict | None = None


class CharacterVoiceAssignmentRequest(BaseModel):
    voice_profile_id: str
