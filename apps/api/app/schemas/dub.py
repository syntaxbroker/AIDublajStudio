from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import SegmentStatus


class DubSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    translation_segment_id: str | None
    timeline_clip_id: str | None
    character_id: str | None
    voice_profile_id: str | None
    text: str | None
    audio_artifact_id: str | None
    provider: str | None
    status: SegmentStatus
    duration_ms: int | None
    similarity_score: float | None = None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime
