from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SpeakerSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    start_ms: int
    end_ms: int
    speaker_label: str
    confidence: float | None
    provider: str | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime
