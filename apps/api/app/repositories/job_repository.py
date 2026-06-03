from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job import Job, JobAttempt
from app.core.enums import JobState


class JobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, job: Job) -> Job:
        self.db.add(job)
        return job

    def add_attempt(self, attempt: JobAttempt) -> JobAttempt:
        self.db.add(attempt)
        return attempt

    def get_by_id(self, job_id: str) -> Job | None:
        return self.db.get(Job, job_id)

    def list_for_project(self, project_id: str) -> list[Job]:
        stmt = select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())
        return list(self.db.scalars(stmt))

    def get_next_queued_job(self, queue_name: str) -> Job | None:
        stmt = (
            select(Job)
            .where(Job.queue_name == queue_name, Job.state == JobState.QUEUED)
            .order_by(Job.created_at.asc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_processing_by_queue(self, queue_name: str) -> list[Job]:
        stmt = select(Job).where(Job.queue_name == queue_name, Job.state == JobState.PROCESSING)
        return list(self.db.scalars(stmt))
