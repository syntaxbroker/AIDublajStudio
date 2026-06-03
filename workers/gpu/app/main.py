import os
import time

from app.db.session import SessionLocal
from app.repositories.job_repository import JobRepository
from app.services.diarization_service import DiarizationService
from app.services.job_service import JobService
from app.services.tts_service import TTSService
from app.services.translation_service import TranslationService
from app.services.transcription_service import TranscriptionService


QUEUE_NAMES = ("transcribe", "diarize", "translate", "tts")
WORKER_NAME = os.getenv("WORKER_NAME", "worker-gpu-0")
POLL_SECONDS = float(os.getenv("GPU_WORKER_POLL_SECONDS", "2"))


def run() -> None:
    with SessionLocal() as db:
        for queue_name in QUEUE_NAMES:
            JobService(db).requeue_processing_jobs(queue_name, WORKER_NAME)

    while True:
        try:
            with SessionLocal() as db:
                for queue_name in QUEUE_NAMES:
                    job = JobRepository(db).get_next_queued_job(queue_name)
                    if not job:
                        continue
                    if queue_name == "transcribe":
                        TranscriptionService(db).process_job(job.id, WORKER_NAME)
                    elif queue_name == "diarize":
                        DiarizationService(db).process_job(job.id, WORKER_NAME)
                    elif queue_name == "translate":
                        TranslationService(db).process_job(job.id, WORKER_NAME)
                    elif queue_name == "tts":
                        TTSService(db).process_job(job.id, WORKER_NAME)
                    break
                else:
                    time.sleep(POLL_SECONDS)
                    continue
                continue
        except Exception as exc:
            print(f"[worker-gpu] job processing error: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
