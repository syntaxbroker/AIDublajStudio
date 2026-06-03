from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.enums import EventType, JobState, JobType
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.job import Job, JobAttempt
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.job import JobResponse
from app.services.event_service import EventService


VALID_TRANSITIONS = {
    JobState.PENDING: {JobState.QUEUED, JobState.CANCELLED},
    JobState.QUEUED: {JobState.PROCESSING, JobState.CANCELLED, JobState.FAILED},
    JobState.PROCESSING: {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.QUEUED},
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}


class JobService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.projects = ProjectRepository(db)
        self.events = EventService(db)

    def create_ingest_job(self, project_id: str, requested_by_user_id: str, artifact_id: str) -> Job:
        job = Job(
            id=str(uuid7()),
            project_id=project_id,
            job_type=JobType.INGEST,
            state=JobState.PENDING,
            queue_name="media",
            requested_by_user_id=requested_by_user_id,
            input_json={"artifact_id": artifact_id},
        )
        self.jobs.create(job)
        self._record_attempt(job, None, JobState.PENDING, "Job created")
        self.transition(job, JobState.QUEUED, worker_name="scheduler")
        return job

    def create_transcribe_job(self, project_id: str, requested_by_user_id: str, artifact_id: str, parent_job_id: str | None = None) -> Job:
        job = Job(
            id=str(uuid7()),
            project_id=project_id,
            parent_job_id=parent_job_id,
            job_type=JobType.TRANSCRIBE,
            state=JobState.PENDING,
            queue_name="transcribe",
            requested_by_user_id=requested_by_user_id,
            input_json={"artifact_id": artifact_id},
        )
        self.jobs.create(job)
        self._record_attempt(job, None, JobState.PENDING, "Job created")
        self.transition(job, JobState.QUEUED, worker_name="scheduler")
        return job

    def create_diarize_job(self, project_id: str, requested_by_user_id: str, artifact_id: str, parent_job_id: str | None = None) -> Job:
        job = Job(
            id=str(uuid7()),
            project_id=project_id,
            parent_job_id=parent_job_id,
            job_type=JobType.DIARIZE,
            state=JobState.PENDING,
            queue_name="diarize",
            requested_by_user_id=requested_by_user_id,
            input_json={"artifact_id": artifact_id},
        )
        self.jobs.create(job)
        self._record_attempt(job, None, JobState.PENDING, "Job created")
        self.transition(job, JobState.QUEUED, worker_name="scheduler")
        return job

    def create_translate_job(self, project_id: str, requested_by_user_id: str, parent_job_id: str | None = None) -> Job:
        job = Job(
            id=str(uuid7()),
            project_id=project_id,
            parent_job_id=parent_job_id,
            job_type=JobType.TRANSLATE,
            state=JobState.PENDING,
            queue_name="translate",
            requested_by_user_id=requested_by_user_id,
            input_json={},
        )
        self.jobs.create(job)
        self._record_attempt(job, None, JobState.PENDING, "Job created")
        self.transition(job, JobState.QUEUED, worker_name="scheduler")
        return job

    def create_tts_job(self, project_id: str, requested_by_user_id: str, parent_job_id: str | None = None) -> Job:
        job = Job(
            id=str(uuid7()),
            project_id=project_id,
            parent_job_id=parent_job_id,
            job_type=JobType.TTS,
            state=JobState.PENDING,
            queue_name="tts",
            requested_by_user_id=requested_by_user_id,
            input_json={},
        )
        self.jobs.create(job)
        self._record_attempt(job, None, JobState.PENDING, "Job created")
        self.transition(job, JobState.QUEUED, worker_name="scheduler")
        return job

    def transition(self, job: Job, next_state: JobState, worker_name: str | None = None, error_message: str | None = None) -> Job:
        allowed = VALID_TRANSITIONS.get(job.state, set())
        if next_state not in allowed:
            raise AppError("INVALID_JOB_TRANSITION", f"Invalid job transition: {job.state} -> {next_state}", 409)

        previous_state = job.state
        now = datetime.now(UTC)
        job.state = next_state
        job.worker_name = worker_name or job.worker_name
        job.updated_at = now

        if next_state == JobState.QUEUED:
            job.queued_at = now
        elif next_state == JobState.PROCESSING:
            job.started_at = now
        elif next_state == JobState.COMPLETED:
            job.completed_at = now
        elif next_state == JobState.CANCELLED:
            job.cancelled_at = now

        self._record_attempt(job, previous_state, next_state, error_message)
        self.events.publish_audit(
            project_id=job.project_id,
            actor_user_id=job.requested_by_user_id,
            related_job_id=job.id,
            entity_type="job",
            entity_id=job.id,
            event_type=EventType.JOB_STATE_CHANGED.value if next_state != JobState.FAILED else EventType.JOB_FAILED.value,
            payload_json={"state_from": previous_state.value if previous_state else None, "state_to": next_state.value},
        )
        return job

    def get_for_user(self, job_id: str, user_id: str) -> JobResponse:
        job = self.jobs.get_by_id(job_id)
        if not job or not self.projects.user_has_access(job.project_id, user_id):
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)
        return JobResponse.model_validate(job)

    def requeue_processing_jobs(self, queue_name: str, worker_name: str) -> int:
        jobs = self.jobs.list_processing_by_queue(queue_name)
        count = 0
        for job in jobs:
            if job.worker_name and job.worker_name != worker_name:
                continue
            self.transition(job, JobState.QUEUED, worker_name=worker_name, error_message="Recovered after worker restart")
            count += 1
        if count:
            self.db.commit()
        return count

    def _record_attempt(self, job: Job, state_from: JobState | None, state_to: JobState, error_message: str | None) -> None:
        existing_attempts = len(job.attempts or [])
        attempt = JobAttempt(
            id=str(uuid7()),
            job_id=job.id,
            attempt_no=existing_attempts + 1,
            worker_name=job.worker_name,
            state_from=state_from,
            state_to=state_to,
            error_message=error_message,
        )
        job.attempts.append(attempt)
        self.jobs.add_attempt(attempt)
