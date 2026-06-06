from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ArtifactType


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    artifact_type: ArtifactType
    status: str
    storage_path: str
    file_name: str
    mime_type: str | None
    size_bytes: int | None
    checksum_sha256: str | None
    duration_ms: int | None
    created_by_job_id: str | None
    metadata_json: dict
    parent_artifact_ids: list[str] = Field(default_factory=list)
    created_at: datetime
