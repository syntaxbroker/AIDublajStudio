from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import JobState, JobType


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    job_type: JobType
    state: JobState
    queue_name: str
    worker_name: str | None
    gpu_device_id: int | None
    input_json: dict
    output_json: dict
    error_json: dict | None
    queued_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobLogResponse(BaseModel):
    job_id: str
    state: JobState
    worker: str | None
    logs: list[str]


class JobRetryResponse(BaseModel):
    old_job_id: str
    new_job_id: str
    status: str


class JobClearResponse(BaseModel):
    job_id: str
    archived: bool


class JobBulkClearRequest(BaseModel):
    project_id: str
    state: JobState


class JobBulkClearResponse(BaseModel):
    archived_count: int
