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

    def create_voice_sample_extract_job(
        self,
        project_id: str,
        requested_by_user_id: str,
        character_id: str,
        parent_job_id: str | None = None,
    ) -> Job:
        job = Job(
            id=str(uuid7()),
            project_id=project_id,
            parent_job_id=parent_job_id,
            job_type=JobType.VOICE_SAMPLE_EXTRACT,
            state=JobState.PENDING,
            queue_name="media",
            requested_by_user_id=requested_by_user_id,
            input_json={"character_id": character_id},
        )
        self.jobs.create(job)
        self._record_attempt(job, None, JobState.PENDING, "Job created")
        self.transition(job, JobState.QUEUED, worker_name="scheduler")
        return job

    def create_audio_mix_job(self, project_id: str, requested_by_user_id: str, parent_job_id: str | None = None) -> Job:
        job = Job(
            id=str(uuid7()),
            project_id=project_id,
            parent_job_id=parent_job_id,
            job_type=JobType.AUDIO_MIX,
            state=JobState.PENDING,
            queue_name="media",
            requested_by_user_id=requested_by_user_id,
            input_json={},
        )
        self.jobs.create(job)
        self._record_attempt(job, None, JobState.PENDING, "Job created")
        self.transition(job, JobState.QUEUED, worker_name="scheduler")
        return job

    def create_lip_sync_job(self, project_id: str, requested_by_user_id: str, parent_job_id: str | None = None) -> Job:
        job = Job(
            id=str(uuid7()),
            project_id=project_id,
            parent_job_id=parent_job_id,
            job_type=JobType.LIP_SYNC,
            state=JobState.PENDING,
            queue_name="media",
            requested_by_user_id=requested_by_user_id,
            input_json={},
        )
        self.jobs.create(job)
        self._record_attempt(job, None, JobState.PENDING, "Job created")
        self.transition(job, JobState.QUEUED, worker_name="scheduler")
        return job

    def create_render_job(self, project_id: str, requested_by_user_id: str, parent_job_id: str | None = None) -> Job:
        job = Job(
            id=str(uuid7()),
            project_id=project_id,
            parent_job_id=parent_job_id,
            job_type=JobType.RENDER,
            state=JobState.PENDING,
            queue_name="media",
            requested_by_user_id=requested_by_user_id,
            input_json={},
        )
        self.jobs.create(job)
        self._record_attempt(job, None, JobState.PENDING, "Job created")
        self.transition(job, JobState.QUEUED, worker_name="scheduler")
        return job

    def retry_for_user(self, job_id: str, user_id: str) -> Job:
        job = self.jobs.get_by_id(job_id)
        if not job or not self.projects.user_has_access(job.project_id, user_id):
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)
        if job.state not in {JobState.FAILED, JobState.CANCELLED}:
            raise AppError("JOB_RETRY_NOT_ALLOWED", "Only FAILED or CANCELLED jobs can be retried", 409)
        active_same_type = next(
            (
                item
                for item in self.jobs.list_for_project(job.project_id)
                if item.job_type == job.job_type
                and item.state in {JobState.PENDING, JobState.QUEUED, JobState.PROCESSING}
            ),
            None,
        )
        if active_same_type:
            raise AppError("JOB_RETRY_BLOCKED_BY_ACTIVE_JOB", "A job of the same type is already active", 409)

        input_json = dict(job.input_json or {})
        if job.job_type == JobType.INGEST:
            artifact_id = input_json.get("artifact_id")
            if not artifact_id:
                raise AppError("JOB_RETRY_INPUT_MISSING", "INGEST retry requires artifact_id", 409)
            new_job = self.create_ingest_job(job.project_id, user_id, artifact_id)
        elif job.job_type == JobType.TRANSCRIBE:
            artifact_id = input_json.get("artifact_id")
            if not artifact_id:
                raise AppError("JOB_RETRY_INPUT_MISSING", "TRANSCRIBE retry requires artifact_id", 409)
            new_job = self.create_transcribe_job(job.project_id, user_id, artifact_id, parent_job_id=job.id)
        elif job.job_type == JobType.DIARIZE:
            artifact_id = input_json.get("artifact_id")
            if not artifact_id:
                raise AppError("JOB_RETRY_INPUT_MISSING", "DIARIZE retry requires artifact_id", 409)
            new_job = self.create_diarize_job(job.project_id, user_id, artifact_id, parent_job_id=job.id)
        elif job.job_type == JobType.TRANSLATE:
            new_job = self.create_translate_job(job.project_id, user_id, parent_job_id=job.id)
        elif job.job_type == JobType.TTS:
            new_job = self.create_tts_job(job.project_id, user_id, parent_job_id=job.id)
        elif job.job_type == JobType.VOICE_SAMPLE_EXTRACT:
            character_id = input_json.get("character_id")
            if not character_id:
                raise AppError("JOB_RETRY_INPUT_MISSING", "VOICE_SAMPLE_EXTRACT retry requires character_id", 409)
            new_job = self.create_voice_sample_extract_job(job.project_id, user_id, character_id, parent_job_id=job.id)
        elif job.job_type == JobType.AUDIO_MIX:
            new_job = self.create_audio_mix_job(job.project_id, user_id, parent_job_id=job.id)
        elif job.job_type == JobType.LIP_SYNC:
            new_job = self.create_lip_sync_job(job.project_id, user_id, parent_job_id=job.id)
        elif job.job_type == JobType.RENDER:
            new_job = self.create_render_job(job.project_id, user_id, parent_job_id=job.id)
        else:
            new_job = Job(
                id=str(uuid7()),
                project_id=job.project_id,
                parent_job_id=job.id,
                job_type=job.job_type,
                state=JobState.PENDING,
                queue_name=job.queue_name,
                requested_by_user_id=user_id,
                input_json=input_json,
            )
            self.jobs.create(new_job)
            self._record_attempt(new_job, None, JobState.PENDING, "Job created by retry")
            self.transition(new_job, JobState.QUEUED, worker_name="scheduler")
        self.append_log(job, f"Retry requested; new job {new_job.id} queued.")
        self.append_log(new_job, f"Retry of job {job.id} queued.")
        self.db.commit()
        self.db.refresh(new_job)
        return new_job

    def clear_for_user(self, job_id: str, user_id: str) -> Job:
        job = self.jobs.get_by_id(job_id)
        if not job or not self.projects.user_has_access(job.project_id, user_id):
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)
        if job.state in {JobState.PENDING, JobState.QUEUED, JobState.PROCESSING}:
            raise AppError("JOB_CLEAR_NOT_ALLOWED", "Active jobs cannot be cleared", 409)
        job.output_json = {**(job.output_json or {}), "archived": True}
        job.updated_at = datetime.now(UTC)
        self.append_log(job, "Job cleared from the UI list.")
        self.db.commit()
        self.db.refresh(job)
        return job

    def bulk_clear_for_user(self, project_id: str, state: JobState, user_id: str) -> int:
        if not self.projects.user_has_access(project_id, user_id):
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
        if state not in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
            raise AppError("JOB_CLEAR_NOT_ALLOWED", "Only completed, failed, or cancelled jobs can be cleared", 409)
        count = 0
        for job in self.jobs.list_for_project(project_id):
            if job.state == state and not (job.output_json or {}).get("archived"):
                job.output_json = {**(job.output_json or {}), "archived": True}
                job.updated_at = datetime.now(UTC)
                self.append_log(job, "Job cleared from the UI list.")
                count += 1
        self.db.commit()
        return count

    def logs_for_user(self, job_id: str, user_id: str) -> list[str]:
        job = self.jobs.get_by_id(job_id)
        if not job or not self.projects.user_has_access(job.project_id, user_id):
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)
        logs: list[str] = []
        for attempt in self.jobs.list_attempts_for_job(job.id):
            state_from = attempt.state_from.value if attempt.state_from else "NONE"
            line = f"{attempt.created_at.isoformat()} {state_from} -> {attempt.state_to.value}"
            if attempt.worker_name:
                line += f" worker={attempt.worker_name}"
            if attempt.error_message:
                line += f" | {attempt.error_message}"
            logs.append(line)
        for item in (job.output_json or {}).get("job_logs") or []:
            timestamp = item.get("timestamp", "")
            message = item.get("message", "")
            logs.append(f"{timestamp} {message}".strip())
        if job.error_json:
            logs.append(f"Failure Reason: {job.error_json.get('message') or job.error_json}")
        if job.state == JobState.PROCESSING:
            logs.append("Job is currently processing. Logs refresh every 5 seconds in the UI.")
        return logs

    def append_log(self, job: Job, message: str, metadata: dict | None = None) -> None:
        output_json = dict(job.output_json or {})
        logs = list(output_json.get("job_logs") or [])
        logs.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "message": message,
                "metadata": metadata or {},
            }
        )
        output_json["job_logs"] = logs[-200:]
        job.output_json = output_json

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
        self.append_log(
            job,
            f"State changed: {previous_state.value if previous_state else 'NONE'} -> {next_state.value}",
            {"worker_name": worker_name, "error_message": error_message},
        )
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
