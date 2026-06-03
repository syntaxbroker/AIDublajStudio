import os
import time

from app.db.session import SessionLocal
from app.repositories.job_repository import JobRepository
from app.services.job_service import JobService
from app.services.media_pipeline_service import MediaPipelineService


QUEUE_NAME = "media"
WORKER_NAME = os.getenv("WORKER_NAME", "worker-media")
POLL_SECONDS = float(os.getenv("MEDIA_WORKER_POLL_SECONDS", "2"))


def run() -> None:
    with SessionLocal() as db:
        JobService(db).requeue_processing_jobs(QUEUE_NAME, WORKER_NAME)

    while True:
        try:
            with SessionLocal() as db:
                job = JobRepository(db).get_next_queued_job(QUEUE_NAME)
                if job:
                    MediaPipelineService(db).process_job(job.id, WORKER_NAME)
                    continue
        except Exception as exc:
            print(f"[worker-media] job processing error: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
