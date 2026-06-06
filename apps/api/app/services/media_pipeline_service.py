import contextlib
import json
import wave
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.enums import ArtifactType, EventType, JobState, MediaProcessingStage
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.artifact import Artifact, ArtifactLink
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.services.event_service import EventService
from app.services.ffmpeg_service import FFmpegService
from app.services.ffprobe_service import FFProbeService
from app.services.job_service import JobService
from app.services.storage_service import StorageService


class MediaPipelineService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.job_service = JobService(db)
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.events = EventService(db)
        self.storage = StorageService()
        self.ffprobe = FFProbeService()
        self.ffmpeg = FFmpegService()

    def process_job(self, job_id: str, worker_name: str) -> None:
        job = self.jobs.get_by_id(job_id)
        if not job:
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)

        source_artifact_id = job.input_json["artifact_id"]
        source_artifact = self.artifacts.get_by_id(source_artifact_id)
        project = self.projects.get_by_id(job.project_id)
        if not source_artifact or not project:
            raise AppError("MEDIA_SOURCE_NOT_FOUND", "Source artifact or project not found", 404)

        try:
            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self._set_stage(job, MediaProcessingStage.UPLOADED)

            source_path = self.storage.absolute_path(source_artifact.storage_path)
            metadata = self.ffprobe.probe(source_path)
            source_width, source_height, source_frame_rate, source_audio_channels, source_sample_rate = self._stream_metrics(metadata)
            source_artifact.duration_ms = self._duration_ms(metadata)
            source_artifact.width = source_width
            source_artifact.height = source_height
            source_artifact.frame_rate = source_frame_rate
            source_artifact.audio_channels = source_audio_channels
            source_artifact.sample_rate = source_sample_rate
            source_artifact.metadata_json = {
                **(source_artifact.metadata_json or {}),
                **metadata,
                "source_width": source_width,
                "source_height": source_height,
                "working_width": source_width,
                "working_height": source_height,
                "resolution_preservation_policy": "source",
            }
            project.metadata_json = {
                **(project.metadata_json or {}),
                "source_width": source_width,
                "source_height": source_height,
                "working_width": source_width,
                "working_height": source_height,
                "resolution_preservation_policy": "source",
            }
            project.updated_at = datetime.now(UTC)
            metadata_artifact = self._create_metadata_artifact(project.storage_key, source_artifact, job.id, metadata)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=metadata_artifact.id,
                event_type=EventType.METADATA_EXTRACTED.value,
                payload_json={"artifact_type": metadata_artifact.artifact_type.value},
            )
            self._set_stage(job, MediaProcessingStage.METADATA_EXTRACTED, metadata_artifact_id=metadata_artifact.id)

            thumbnail_artifact = self._create_thumbnail_artifact(project.storage_key, source_artifact, job.id, source_path)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=thumbnail_artifact.id,
                event_type=EventType.THUMBNAIL_GENERATED.value,
                payload_json={"artifact_type": thumbnail_artifact.artifact_type.value},
            )

            proxy_artifact = self._create_proxy_artifact(project.storage_key, source_artifact, job.id, source_path)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=proxy_artifact.id,
                event_type=EventType.PROXY_GENERATED.value,
                payload_json={"artifact_type": proxy_artifact.artifact_type.value},
            )
            self._set_stage(job, MediaProcessingStage.PROXY_GENERATED, proxy_artifact_id=proxy_artifact.id)

            waveform_artifact = self._create_waveform_artifact(project.storage_key, source_artifact, job.id, source_path)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=waveform_artifact.id,
                event_type=EventType.WAVEFORM_GENERATED.value,
                payload_json={"artifact_type": waveform_artifact.artifact_type.value},
            )

            self._set_stage(
                job,
                MediaProcessingStage.READY_FOR_TRANSCRIPTION,
                metadata_artifact_id=metadata_artifact.id,
                thumbnail_artifact_id=thumbnail_artifact.id,
                proxy_artifact_id=proxy_artifact.id,
                waveform_artifact_id=waveform_artifact.id,
            )
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.MEDIA_READY_FOR_TRANSCRIPTION.value,
                payload_json={"media_stage": MediaProcessingStage.READY_FOR_TRANSCRIPTION.value},
            )
            self.job_service.create_transcribe_job(
                project_id=project.id,
                requested_by_user_id=job.requested_by_user_id,
                artifact_id=proxy_artifact.id,
                parent_job_id=job.id,
            )
            self.job_service.transition(job, JobState.COMPLETED, worker_name=worker_name)
            self.db.commit()
        except Exception as exc:
            job.error_json = {"message": str(exc)}
            self.job_service.transition(job, JobState.FAILED, worker_name=worker_name, error_message=str(exc))
            self.db.commit()
            raise

    def _set_stage(self, job, stage: MediaProcessingStage, **extra: str) -> None:
        output = dict(job.output_json or {})
        output["media_stage"] = stage.value
        output.update(extra)
        job.output_json = output
        job.updated_at = datetime.now(UTC)

    def _create_metadata_artifact(self, storage_key: str, parent_artifact: Artifact, job_id: str, metadata: dict) -> Artifact:
        relative_path, size_bytes, checksum = self.storage.write_json(
            storage_key,
            "metadata",
            f"{uuid7()}-metadata.json",
            metadata,
        )
        return self._create_child_artifact(
            parent_artifact=parent_artifact,
            job_id=job_id,
            artifact_type=ArtifactType.VIDEO_METADATA,
            relative_path=relative_path,
            file_name=Path(relative_path).name,
            mime_type="application/json",
            size_bytes=size_bytes,
            checksum_sha256=checksum,
            metadata_json=metadata,
        )

    def _create_thumbnail_artifact(self, storage_key: str, parent_artifact: Artifact, job_id: str, source_path: Path) -> Artifact:
        base = self.storage.ensure_project_structure(storage_key)
        output_path = base / "thumbnails" / f"{uuid7()}.jpg"
        self.ffmpeg.generate_thumbnail(source_path, output_path)
        relative_path = output_path.relative_to(self.storage.root).as_posix()
        payload = output_path.read_bytes()
        checksum = self._sha256(payload)
        return self._create_child_artifact(
            parent_artifact=parent_artifact,
            job_id=job_id,
            artifact_type=ArtifactType.THUMBNAIL,
            relative_path=relative_path,
            file_name=output_path.name,
            mime_type="image/jpeg",
            size_bytes=len(payload),
            checksum_sha256=checksum,
        )

    def _create_proxy_artifact(self, storage_key: str, parent_artifact: Artifact, job_id: str, source_path: Path) -> Artifact:
        base = self.storage.ensure_project_structure(storage_key)
        output_path = base / "proxies" / f"{uuid7()}-proxy.mp4"
        self.ffmpeg.generate_proxy(source_path, output_path)
        metadata = self.ffprobe.probe(output_path)
        payload = output_path.read_bytes()
        checksum = self._sha256(payload)
        duration_ms = self._duration_ms(metadata)
        width, height, frame_rate, audio_channels, sample_rate = self._stream_metrics(metadata)
        source_width = parent_artifact.width or (parent_artifact.metadata_json or {}).get("source_width")
        source_height = parent_artifact.height or (parent_artifact.metadata_json or {}).get("source_height")
        return self._create_child_artifact(
            parent_artifact=parent_artifact,
            job_id=job_id,
            artifact_type=ArtifactType.PROXY_VIDEO,
            relative_path=output_path.relative_to(self.storage.root).as_posix(),
            file_name=output_path.name,
            mime_type="video/mp4",
            size_bytes=len(payload),
            checksum_sha256=checksum,
            duration_ms=duration_ms,
            width=width,
            height=height,
            frame_rate=frame_rate,
            audio_channels=audio_channels,
            sample_rate=sample_rate,
            metadata_json={
                **metadata,
                "source_width": source_width,
                "source_height": source_height,
                "working_width": width,
                "working_height": height,
                "resolution_preserved": bool(source_width == width and source_height == height),
                "resolution_preservation_policy": "source",
            },
        )

    def _create_waveform_artifact(self, storage_key: str, parent_artifact: Artifact, job_id: str, source_path: Path) -> Artifact:
        base = self.storage.ensure_project_structure(storage_key)
        wav_path = base / "waveforms" / f"{uuid7()}.wav"
        self.ffmpeg.extract_waveform_audio(source_path, wav_path)
        waveform_payload = self._compute_waveform(wav_path)
        relative_path, size_bytes, checksum = self.storage.write_json(
            storage_key,
            "waveforms",
            f"{uuid7()}-waveform.json",
            waveform_payload,
        )
        with contextlib.suppress(FileNotFoundError):
            wav_path.unlink()
        return self._create_child_artifact(
            parent_artifact=parent_artifact,
            job_id=job_id,
            artifact_type=ArtifactType.WAVEFORM_JSON,
            relative_path=relative_path,
            file_name=Path(relative_path).name,
            mime_type="application/json",
            size_bytes=size_bytes,
            checksum_sha256=checksum,
            metadata_json=waveform_payload,
        )

    def _create_child_artifact(
        self,
        *,
        parent_artifact: Artifact,
        job_id: str,
        artifact_type: ArtifactType,
        relative_path: str,
        file_name: str,
        mime_type: str,
        size_bytes: int,
        checksum_sha256: str,
        duration_ms: int | None = None,
        width: int | None = None,
        height: int | None = None,
        frame_rate: float | None = None,
        audio_channels: int | None = None,
        sample_rate: int | None = None,
        metadata_json: dict | None = None,
    ) -> Artifact:
        artifact = Artifact(
            id=str(uuid7()),
            project_id=parent_artifact.project_id,
            created_by_job_id=job_id,
            artifact_type=artifact_type,
            storage_path=relative_path,
            file_name=file_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
            duration_ms=duration_ms,
            width=width,
            height=height,
            frame_rate=frame_rate,
            audio_channels=audio_channels,
            sample_rate=sample_rate,
            metadata_json=metadata_json or {},
        )
        self.artifacts.create(artifact)
        self.artifacts.create_link(
            ArtifactLink(
                id=str(uuid7()),
                parent_artifact_id=parent_artifact.id,
                child_artifact_id=artifact.id,
                relation="derived_from",
            )
        )
        return artifact

    def _compute_waveform(self, wav_path: Path, buckets: int = 200) -> dict:
        with wave.open(str(wav_path), "rb") as wav_file:
            frame_count = wav_file.getnframes()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.readframes(frame_count)
            sample_max = float(2 ** (8 * sample_width - 1))
            step = max(1, frame_count // buckets)
            points: list[float] = []
            for index in range(0, frame_count, step):
                chunk = frames[index * sample_width : min(len(frames), (index + step) * sample_width)]
                if not chunk:
                    continue
                peak = 0
                for offset in range(0, len(chunk), sample_width):
                    value = int.from_bytes(chunk[offset : offset + sample_width], byteorder="little", signed=True)
                    peak = max(peak, abs(value))
                points.append(round(peak / sample_max, 6))
            return {"points": points, "bucket_count": len(points)}

    def _duration_ms(self, metadata: dict) -> int | None:
        duration = metadata.get("format", {}).get("duration")
        if duration is None:
            return None
        return int(float(duration) * 1000)

    def _stream_metrics(self, metadata: dict) -> tuple[int | None, int | None, float | None, int | None, int | None]:
        video = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"), {})
        audio = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "audio"), {})
        rate = video.get("avg_frame_rate", "0/1")
        try:
            numerator, denominator = rate.split("/")
            frame_rate = round(float(numerator) / float(denominator), 3) if float(denominator) else None
        except Exception:
            frame_rate = None
        return (
            video.get("width"),
            video.get("height"),
            frame_rate,
            audio.get("channels"),
            int(audio["sample_rate"]) if audio.get("sample_rate") else None,
        )

    def _sha256(self, payload: bytes) -> str:
        import hashlib

        return hashlib.sha256(payload).hexdigest()
