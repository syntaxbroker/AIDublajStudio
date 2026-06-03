from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import SegmentStatus, TranscriptSource


class TranscriptSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    source_artifact_id: str | None
    segment_index: int
    start_ms: int
    end_ms: int
    speaker_label: str | None
    language_code: str | None
    text: str
    confidence: float | None
    source: TranscriptSource
    status: SegmentStatus
    metadata_json: dict
    created_at: datetime
    updated_at: datetime

