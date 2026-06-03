from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import SegmentStatus


class TranslationSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    transcript_segment_id: str
    source_language: str | None
    target_language: str
    source_text: str | None
    translated_text: str
    provider: str | None
    status: SegmentStatus
    metadata_json: dict
    created_at: datetime
    updated_at: datetime
