from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import AppError
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.db.session import get_db
from app.schemas.job import (
    JobBulkClearRequest,
    JobBulkClearResponse,
    JobClearResponse,
    JobLogResponse,
    JobResponse,
    JobRetryResponse,
)
from app.services.job_service import JobService


router = APIRouter()


@router.post("/clear", response_model=JobBulkClearResponse, responses=COMMON_ERROR_RESPONSES)
def clear_jobs(
    payload: JobBulkClearRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> JobBulkClearResponse:
    count = JobService(db).bulk_clear_for_user(payload.project_id, payload.state, current_user.id)
    return JobBulkClearResponse(archived_count=count)


@router.get("/{job_id}", response_model=JobResponse, responses=COMMON_ERROR_RESPONSES)
def get_job(job_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)) -> JobResponse:
    return JobService(db).get_for_user(job_id, current_user.id)


@router.get("/{job_id}/logs", response_model=JobLogResponse, responses=COMMON_ERROR_RESPONSES)
def get_job_logs(job_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)) -> JobLogResponse:
    service = JobService(db)
    job = service.jobs.get_by_id(job_id)
    if not job or not service.projects.user_has_access(job.project_id, current_user.id):
        raise AppError("JOB_NOT_FOUND", "Job not found", 404)
    return JobLogResponse(
        job_id=job.id,
        state=job.state,
        worker=job.worker_name,
        logs=service.logs_for_user(job_id, current_user.id),
    )


@router.post("/{job_id}/retry", response_model=JobRetryResponse, responses=COMMON_ERROR_RESPONSES)
def retry_job(job_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)) -> JobRetryResponse:
    new_job = JobService(db).retry_for_user(job_id, current_user.id)
    return JobRetryResponse(old_job_id=job_id, new_job_id=new_job.id, status="queued")


@router.post("/{job_id}/clear", response_model=JobClearResponse, responses=COMMON_ERROR_RESPONSES)
def clear_job(job_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)) -> JobClearResponse:
    job = JobService(db).clear_for_user(job_id, current_user.id)
    return JobClearResponse(job_id=job.id, archived=True)
