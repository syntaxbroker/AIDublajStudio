from datetime import UTC, datetime
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

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
    MIN_REFERENCE_DURATION_MS = 15_000
    TARGET_REFERENCE_MIN_MS = 20_000
    TARGET_REFERENCE_MAX_MS = 40_000
    MIN_CLIP_DURATION_MS = 1_200
    REFERENCE_SAMPLE_RATE = 22_050

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

            selected_clips = self._select_reference_clips(clips)
            speaker_label = selected_clips[0].speaker_label
            prompt_text = self._build_prompt_text(selected_clips)
            selected_source_duration_ms = sum(self._clip_duration_ms(clip) for clip in selected_clips)
            character_display_name = (character.display_name or "").strip()
            voice_sample_name = f"{character_display_name} Preview" if character_display_name else "Voice Sample Preview"
            voice_reference_name = f"{character_display_name} Reference" if character_display_name else "Voice Reference"
            file_name_prefix = self._safe_file_name(character_display_name or "voice-sample")

            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.VOICE_SAMPLE_EXTRACTION_STARTED.value,
                payload_json={
                    "character_id": character.id,
                    "character_display_name": character_display_name,
                    "voice_sample_name": voice_sample_name,
                    "speaker_label": speaker_label,
                    "selected_clip_count": len(selected_clips),
                    "selected_duration_ms": selected_source_duration_ms,
                },
            )

            sample_path = self.storage.ensure_project_structure(project.storage_key) / "voice_samples" / f"{file_name_prefix}-{uuid7()}-sample.wav"
            self._build_reference_audio(source_path, sample_path, selected_clips)
            sample_metadata = self.ffprobe.probe(sample_path)
            sample_payload = sample_path.read_bytes()
            sample_duration_ms = self._duration_ms(sample_metadata)
            volume_metadata = self._probe_volume(sample_path)
            sample_quality_score = self._sample_quality_score(
                duration_ms=sample_duration_ms or 0,
                clip_count=len(selected_clips),
                volume_metadata=volume_metadata,
            )
            warning = self._short_sample_warning(sample_duration_ms or 0)
            timeline_clip_ids = [clip.id for clip in selected_clips]
            sample_processing_metadata = {
                "character_id": character.id,
                "character_display_name": character_display_name,
                "voice_sample_name": voice_sample_name,
                "voice_reference_name": voice_reference_name,
                "speaker_label": speaker_label,
                "timeline_clip_ids": timeline_clip_ids,
                "timeline_clip_id": selected_clips[0].id,
                "source_clip_count": len(selected_clips),
                "selected_source_duration_ms": selected_source_duration_ms,
                "prompt_text": prompt_text,
                "source_language": project.source_language,
                "target_language": project.target_language,
                "reference_language": project.source_language,
                "reference_duration_ms": sample_duration_ms,
                "sample_quality_score": sample_quality_score,
                "normalized": True,
                "silence_trimmed": True,
                **volume_metadata,
            }
            if warning:
                sample_processing_metadata["warning"] = warning

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
                duration_ms=sample_duration_ms,
                audio_channels=self._audio_channels(sample_metadata),
                sample_rate=self._sample_rate(sample_metadata),
                metadata_json={
                    **sample_metadata,
                    **sample_processing_metadata,
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

            reference_path = self.storage.ensure_project_structure(project.storage_key) / "voice_references" / f"{file_name_prefix}-{uuid7()}-reference.wav"
            reference_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sample_path, reference_path)
            reference_payload = reference_path.read_bytes()
            reference_artifact = Artifact(
                id=str(uuid7()),
                project_id=project.id,
                created_by_job_id=job.id,
                artifact_type=ArtifactType.VOICE_REFERENCE_AUDIO,
                storage_path=reference_path.relative_to(self.storage.root).as_posix(),
                file_name=reference_path.name,
                mime_type="audio/wav",
                size_bytes=len(reference_payload),
                checksum_sha256=self._sha256(reference_payload),
                duration_ms=sample_artifact.duration_ms,
                audio_channels=sample_artifact.audio_channels,
                sample_rate=sample_artifact.sample_rate,
                metadata_json={
                    **sample_metadata,
                    **sample_processing_metadata,
                    "sample_artifact_id": sample_artifact.id,
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
                "character_display_name": character_display_name,
                "voice_sample_name": voice_sample_name,
                "voice_reference_name": voice_reference_name,
                "speaker_label": speaker_label,
                "voice_sample_artifact_id": sample_artifact.id,
                "voice_reference_artifact_id": reference_artifact.id,
                "reference_duration_ms": reference_artifact.duration_ms,
                "sample_quality_score": sample_quality_score,
                "selected_clip_count": len(selected_clips),
                "normalized": True,
                "silence_trimmed": True,
            }
            if warning:
                job.output_json["warning"] = warning
            job.updated_at = datetime.now(UTC)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=sample_artifact.id,
                event_type=EventType.VOICE_SAMPLE_AUDIO_CREATED.value,
                payload_json={
                    "artifact_type": sample_artifact.artifact_type.value,
                    "character_id": character.id,
                    "character_display_name": character_display_name,
                    "voice_sample_name": voice_sample_name,
                    "reference_duration_ms": sample_artifact.duration_ms,
                    "sample_quality_score": sample_quality_score,
                    "warning": warning,
                },
            )
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="artifact",
                entity_id=reference_artifact.id,
                event_type=EventType.VOICE_SAMPLE_AUDIO_CREATED.value,
                payload_json={
                    "artifact_type": reference_artifact.artifact_type.value,
                    "character_id": character.id,
                    "character_display_name": character_display_name,
                    "voice_reference_name": voice_reference_name,
                    "reference_duration_ms": reference_artifact.duration_ms,
                    "sample_quality_score": sample_quality_score,
                    "warning": warning,
                },
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

    def _select_reference_clips(self, clips):
        chronological = sorted(clips, key=lambda item: (item.start_ms, item.end_ms))
        eligible = [clip for clip in chronological if self._clip_duration_ms(clip) >= self.MIN_CLIP_DURATION_MS]
        candidates = eligible or chronological
        selected = []
        total_ms = 0
        for clip in candidates:
            if total_ms >= self.TARGET_REFERENCE_MIN_MS:
                break
            duration_ms = self._clip_duration_ms(clip)
            if total_ms + duration_ms > self.TARGET_REFERENCE_MAX_MS and selected:
                continue
            selected.append(clip)
            total_ms += duration_ms
        if not selected:
            raise AppError("VOICE_SAMPLE_SOURCE_SEGMENTS_NOT_FOUND", "Character does not have source segments for sample extraction", 400)
        return selected

    def _build_reference_audio(self, source_path: Path, output_path: Path, clips) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="voice-reference-") as tmpdir:
            temp_root = Path(tmpdir)
            processed_paths = []
            for index, clip in enumerate(clips):
                raw_path = temp_root / f"{index:03d}-raw.wav"
                processed_path = temp_root / f"{index:03d}-processed.wav"
                self.ffmpeg.extract_audio_segment(
                    source_path,
                    raw_path,
                    int(clip.start_ms),
                    int(clip.end_ms),
                    sample_rate=self.REFERENCE_SAMPLE_RATE,
                )
                try:
                    self._trim_and_normalize(raw_path, processed_path)
                except subprocess.CalledProcessError:
                    continue
                if not processed_path.exists():
                    continue
                duration_ms = self._duration_ms(self.ffprobe.probe(processed_path)) or 0
                if duration_ms < 500:
                    continue
                volume_metadata = self._probe_volume(processed_path)
                if volume_metadata.get("mean_volume_db", 0) < -45:
                    continue
                processed_paths.append(processed_path)

            if not processed_paths:
                raise AppError("VOICE_REFERENCE_EMPTY", "Voice reference extraction produced no usable audio", 409)

            concat_file = temp_root / "concat.txt"
            concat_file.write_text(
                "".join(f"file '{path.as_posix()}'\n" for path in processed_paths),
                encoding="utf-8",
            )
            command = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-ac",
                "1",
                "-ar",
                str(self.REFERENCE_SAMPLE_RATE),
                str(output_path),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            self._trim_and_normalize(output_path, output_path)

    def _trim_and_normalize(self, source_path: Path, output_path: Path) -> None:
        filter_chain = (
            "silenceremove="
            "start_periods=1:start_duration=0.10:start_threshold=-45dB:"
            "stop_periods=1:stop_duration=0.20:stop_threshold=-45dB,"
            "loudnorm=I=-18:TP=-1.5:LRA=11"
        )
        temp_output = output_path
        if source_path == output_path:
            temp_output = output_path.with_name(f"{output_path.stem}-normalized{output_path.suffix}")
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-af",
            filter_chain,
            "-ac",
            "1",
            "-ar",
            str(self.REFERENCE_SAMPLE_RATE),
            str(temp_output),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        if temp_output != output_path:
            temp_output.replace(output_path)

    def _build_prompt_text(self, clips) -> str | None:
        parts = [(clip.text or "").strip() for clip in clips if (clip.text or "").strip()]
        if not parts:
            return None
        text = " ".join(parts)
        return text[:1200]

    def _clip_duration_ms(self, clip) -> int:
        return max(int(clip.end_ms or 0) - int(clip.start_ms or 0), 0)

    def _probe_volume(self, audio_path: Path) -> dict:
        command = ["ffmpeg", "-i", str(audio_path), "-af", "volumedetect", "-f", "null", "-"]
        result = subprocess.run(command, capture_output=True, text=True)
        output = result.stderr or ""
        metadata = {}
        mean_match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", output)
        max_match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", output)
        if mean_match:
            metadata["mean_volume_db"] = float(mean_match.group(1))
        if max_match:
            metadata["max_volume_db"] = float(max_match.group(1))
        return metadata

    def _sample_quality_score(self, *, duration_ms: int, clip_count: int, volume_metadata: dict) -> float:
        if duration_ms <= 0:
            return 0.0
        if duration_ms >= self.TARGET_REFERENCE_MIN_MS:
            duration_score = 1.0
        else:
            duration_score = max(0.0, min(duration_ms / self.TARGET_REFERENCE_MIN_MS, 1.0))

        clip_score = min(max(clip_count, 1) / 3, 1.0)
        mean_volume = volume_metadata.get("mean_volume_db")
        if mean_volume is None:
            volume_score = 0.75
        elif mean_volume < -45:
            volume_score = 0.15
        elif mean_volume < -34 or mean_volume > -10:
            volume_score = 0.7
        else:
            volume_score = 1.0
        score = (duration_score * 0.55) + (volume_score * 0.25) + (clip_score * 0.20)
        return round(max(0.0, min(score, 1.0)), 3)

    def _short_sample_warning(self, duration_ms: int) -> dict | None:
        if duration_ms >= self.MIN_REFERENCE_DURATION_MS:
            return None
        return {
            "code": "VOICE_REFERENCE_SHORT_FOR_CLONE_QUALITY",
            "message": "Voice reference is shorter than 15 seconds; clone quality may be robotic.",
            "reference_duration_ms": duration_ms,
            "minimum_recommended_duration_ms": self.MIN_REFERENCE_DURATION_MS,
        }

    def _safe_file_name(self, value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
        return normalized.lower()[:48] or "voice-sample"

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
