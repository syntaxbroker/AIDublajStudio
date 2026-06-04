from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.enums import ArtifactType, EventType, JobState
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.artifact import Artifact, ArtifactLink
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.character_repository import CharacterRepository
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.timeline_repository import TimelineRepository
from app.services.event_service import EventService
from app.services.ffmpeg_service import FFmpegService
from app.services.ffprobe_service import FFProbeService
from app.services.job_service import JobService
from app.services.storage_service import StorageService


class VoiceSampleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.job_service = JobService(db)
        self.projects = ProjectRepository(db)
        self.characters = CharacterRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.timeline = TimelineRepository(db)
        self.events = EventService(db)
        self.ffmpeg = FFmpegService()
        self.ffprobe = FFProbeService()
        self.storage = StorageService()

    def create_job_for_character(
        self,
        project_id: str,
        character_id: str,
        current_user_id: str,
        parent_job_id: str | None = None,
        *,
        auto_commit: bool = True,
    ):
        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
        character = self.characters.get_character(character_id)
        if not character or character.project_id != project_id:
            raise AppError("CHARACTER_NOT_FOUND", "Character not found", 404)
        if not self._find_character_clips(project_id, character_id):
            raise AppError("VOICE_SAMPLE_SOURCE_SEGMENTS_NOT_FOUND", "Character does not have source segments for sample extraction", 400)

        job = self.job_service.create_voice_sample_extract_job(project_id, current_user_id, character_id, parent_job_id=parent_job_id)
        if auto_commit:
            self.db.commit()
            self.db.refresh(job)
        return job

    def process_job(self, job_id: str, worker_name: str) -> None:
        job = self.jobs.get_by_id(job_id)
        if not job:
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)

        project = self.projects.get_by_id(job.project_id)
        try:
            if not project:
                raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)

            character_id = str((job.input_json or {}).get("character_id") or "")
            character = self.characters.get_character(character_id)
            if not character or character.project_id != project.id:
                raise AppError("CHARACTER_NOT_FOUND", "Character not found", 404)

            clips = self._find_character_clips(project.id, character.id)
            if not clips:
                raise AppError("VOICE_SAMPLE_SOURCE_SEGMENTS_NOT_FOUND", "Character does not have source segments for sample extraction", 400)

            source_artifact = self._find_source_video_artifact(project.id)
            if not source_artifact:
                raise AppError("SOURCE_VIDEO_NOT_FOUND", "Source video not found", 404)

            source_path = self.storage.absolute_path(source_artifact.storage_path)
            if not source_path.exists():
                raise AppError("SOURCE_VIDEO_FILE_NOT_FOUND", "Source video file not found", 404)

            target_clip = clips[0]
            speaker_label = target_clip.speaker_label
            prompt_text = (target_clip.text or "").strip() or None

            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.VOICE_SAMPLE_EXTRACTION_STARTED.value,
                payload_json={"character_id": character.id, "speaker_label": speaker_label},
            )

            sample_path = self.storage.ensure_project_structure(project.storage_key) / "voice_samples" / f"{uuid7()}-sample.wav"
            self.ffmpeg.extract_audio_segment(source_path, sample_path, target_clip.start_ms, target_clip.end_ms)
            sample_metadata = self.ffprobe.probe(sample_path)
            sample_payload = sample_path.read_bytes()

            sample_artifact = Artifact(
                id=str(uuid7()),
                project_id=project.id,
                created_by_job_id=job.id,
                artifact_type=ArtifactType.VOICE_SAMPLE_AUDIO,
                storage_path=sample_path.relative_to(self.storage.root).as_posix(),
                file_name=sample_path.name,
                mime_type="audio/wav",
                size_bytes=len(sample_payload),
                checksum_sha256=self._sha256(sample_payload),
                duration_ms=self._duration_ms(sample_metadata),
                audio_channels=self._audio_channels(sample_metadata),
                sample_rate=self._sample_rate(sample_metadata),
                metadata_json={
                    **sample_metadata,
                    "character_id": character.id,
                    "speaker_label": speaker_label,
                    "timeline_clip_id": target_clip.id,
                    "prompt_text": prompt_text,
                },
            )
            self.artifacts.create(sample_artifact)
            self.artifacts.create_link(
                ArtifactLink(
                    id=str(uuid7()),
                    parent_artifact_id=source_artifact.id,
                    child_artifact_id=sample_artifact.id,
                    relation="voice_sample_from",
                )
            )
            self.db.flush()

            reference_relative, reference_size, reference_checksum = self.storage.write_bytes(
                project.storage_key,
                "voice_references",
                f"{uuid7()}-reference.wav",
                sample_payload,
            )
            reference_artifact = Artifact(
                id=str(uuid7()),
                project_id=project.id,
                created_by_job_id=job.id,
                artifact_type=ArtifactType.VOICE_REFERENCE_AUDIO,
                storage_path=reference_relative,
                file_name=Path(reference_relative).name,
                mime_type="audio/wav",
                size_bytes=reference_size,
                checksum_sha256=reference_checksum,
                duration_ms=sample_artifact.duration_ms,
                audio_channels=sample_artifact.audio_channels,
                sample_rate=sample_artifact.sample_rate,
                metadata_json={
                    **sample_metadata,
                    "character_id": character.id,
                    "speaker_label": speaker_label,
                    "sample_artifact_id": sample_artifact.id,
                    "timeline_clip_id": target_clip.id,
                    "prompt_text": prompt_text,
                },
            )
            self.artifacts.create(reference_artifact)
            self.artifacts.create_link(
                ArtifactLink(
                    id=str(uuid7()),
                    parent_artifact_id=sample_artifact.id,
                    child_artifact_id=reference_artifact.id,
                    relation="voice_reference_from",
                )
            )
            self.db.flush()

            job.output_json = {
                **(job.output_json or {}),
                "character_id": character.id,
                "speaker_label": speaker_label,
                "voice_sample_artifact_id": sample_artifact.id,
                "voice_reference_artifact_id": reference_artifact.id,
            }
            job.updated_at = datetime.now(UTC)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=sample_artifact.id,
                event_type=EventType.VOICE_SAMPLE_AUDIO_CREATED.value,
                payload_json={"artifact_type": sample_artifact.artifact_type.value, "character_id": character.id},
            )
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=reference_artifact.id,
                event_type=EventType.VOICE_SAMPLE_AUDIO_CREATED.value,
                payload_json={"artifact_type": reference_artifact.artifact_type.value, "character_id": character.id},
            )

            self.job_service.transition(job, JobState.COMPLETED, worker_name=worker_name)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            failed_job = self.jobs.get_by_id(job_id)
            if failed_job:
                failed_job.error_json = {"message": str(exc)}
                self.job_service.transition(failed_job, JobState.FAILED, worker_name=worker_name, error_message=str(exc))
            self.db.commit()
            raise

    def _find_character_clips(self, project_id: str, character_id: str):
        clips = [
            clip
            for clip in self.timeline.list_clips_for_project(project_id)
            if clip.character_id == character_id and clip.start_ms < clip.end_ms
        ]
        clips.sort(key=lambda item: (item.end_ms - item.start_ms), reverse=True)
        return clips

    def _find_source_video_artifact(self, project_id: str):
        return next(
            (artifact for artifact in self.artifacts.list_for_project(project_id) if artifact.artifact_type == ArtifactType.SOURCE_VIDEO),
            None,
        )

    def _duration_ms(self, metadata: dict) -> int | None:
        duration = metadata.get("format", {}).get("duration")
        if duration is None:
            return None
        return int(float(duration) * 1000)

    def _audio_channels(self, metadata: dict) -> int | None:
        audio = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "audio"), {})
        return audio.get("channels")

    def _sample_rate(self, metadata: dict) -> int | None:
        audio = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "audio"), {})
        return int(audio["sample_rate"]) if audio.get("sample_rate") else None

    def _sha256(self, payload: bytes) -> str:
        import hashlib

        return hashlib.sha256(payload).hexdigest()
