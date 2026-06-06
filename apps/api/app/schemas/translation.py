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
    faithful_text: str | None = None
    adapted_text: str | None = None
    translated_text: str
    provider: str | None
    duration_target_ms: int | None = None
    semantic_similarity_score: float | None = None
    status: SegmentStatus
    metadata_json: dict
    created_at: datetime
    updated_at: datetime
