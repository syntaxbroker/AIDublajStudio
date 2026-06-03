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
    created_at: datetime
    updated_at: datetime
