import os
import time
import logging
from datetime import UTC, datetime

from app.db.session import SessionLocal
from app.core.enums import JobType
from app.repositories.job_repository import JobRepository
from app.services.lip_sync_service import LipSyncService
from app.services.render_service import RenderService
from app.services.audio_mix_service import AudioMixService
from app.services.job_service import JobService
from app.services.media_pipeline_service import MediaPipelineService
from app.services.voice_sample_service import VoiceSampleService


QUEUE_NAME = "media"
WORKER_NAME = os.getenv("WORKER_NAME", "worker-media")
POLL_SECONDS = float(os.getenv("MEDIA_WORKER_POLL_SECONDS", "2"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("worker-media")


def run() -> None:
    with SessionLocal() as db:
        JobService(db).requeue_processing_jobs(QUEUE_NAME, WORKER_NAME)

    while True:
        try:
            with SessionLocal() as db:
                job = JobRepository(db).get_next_queued_job(QUEUE_NAME)
                if job:
                    logger.info(
                        "Dispatching media job",
                        extra={
                            "job_id": job.id,
                            "job_type": job.job_type.value,
                            "queue_name": job.queue_name,
                            "dispatch_time": datetime.now(UTC).isoformat(),
                        },
                    )
                    if job.job_type == JobType.AUDIO_MIX:
                        AudioMixService(db).process_job(job.id, WORKER_NAME)
                    elif job.job_type == JobType.LIP_SYNC:
                        LipSyncService(db).process_job(job.id, WORKER_NAME)
                    elif job.job_type == JobType.VOICE_SAMPLE_EXTRACT:
                        VoiceSampleService(db).process_job(job.id, WORKER_NAME)
                    elif job.job_type == JobType.RENDER:
                        RenderService(db).process_job(job.id, WORKER_NAME)
                    else:
                        MediaPipelineService(db).process_job(job.id, WORKER_NAME)
                    continue
        except Exception as exc:
            print(f"[worker-media] job processing error: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
