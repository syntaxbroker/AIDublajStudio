from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.db.session import get_db
from app.schemas.job import JobResponse
from app.services.job_service import JobService


router = APIRouter()


@router.get("/{job_id}", response_model=JobResponse, responses=COMMON_ERROR_RESPONSES)
def get_job(job_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)) -> JobResponse:
    return JobService(db).get_for_user(job_id, current_user.id)
