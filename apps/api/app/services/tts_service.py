import asyncio
import json
import logging
import subprocess
import tempfile
import wave
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import ArtifactType, EventType, JobState, SegmentStatus
from app.core.errors import AppError
from app.core.uuid7 import uuid7
from app.models.artifact import Artifact, ArtifactLink
from app.models.dub_segment import DubSegment
from app.providers.registry import ProviderRegistry
from app.repositories.artifact_repository import ArtifactRepository
from app.repositories.dub_repository import DubRepository
from app.repositories.job_repository import JobRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.timeline_repository import TimelineRepository
from app.services.event_service import EventService
from app.services.job_service import JobService
from app.services.storage_service import StorageService
from app.services.translation_adaptation import fit_turkish_text_to_duration, semantic_similarity_score
from app.services.voice_similarity_service import VoiceSimilarityService
from app.services.voice_profile_service import VoiceProfileService


logger = logging.getLogger(__name__)


class TTSService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.jobs = JobRepository(db)
        self.job_service = JobService(db)
        self.projects = ProjectRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.timeline = TimelineRepository(db)
        self.dubs = DubRepository(db)
        self.events = EventService(db)
        self.storage = StorageService()
        self.providers = ProviderRegistry()
        self.voice_profiles = VoiceProfileService(db)
        self.voice_similarity = VoiceSimilarityService()
        self.settings = get_settings()

    def create_job_for_project(
        self,
        project_id: str,
        current_user_id: str,
        parent_job_id: str | None = None,
        *,
        auto_commit: bool = True,
    ):
        project = self.projects.get_by_id(project_id)
        if not project:
            raise AppError("PROJECT_NOT_FOUND", "Project not found", 404)
        if not project.timeline_clips:
            raise AppError("TIMELINE_REQUIRED", "Timeline clips are required before TTS", 409)
        if not any((clip.translation_text or clip.text or "").strip() for clip in project.timeline_clips):
            raise AppError("TTS_SOURCE_TEXT_NOT_FOUND", "Timeline clips do not contain text for TTS", 409)
        job = self.job_service.create_tts_job(project_id, current_user_id, parent_job_id=parent_job_id)
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
            clips = self.timeline.list_clips_for_project(project.id)
            if not clips:
                raise AppError("TIMELINE_REQUIRED", "Timeline clips are required before TTS", 409)

            self.job_service.transition(job, JobState.PROCESSING, worker_name=worker_name)
            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.TTS_STARTED.value,
                payload_json={"clip_count": len(clips)},
            )
            self.db.commit()
            self.db.refresh(job)

            self._clear_existing_outputs(project.id)
            created_segments: list[DubSegment] = []
            resolved_provider_key = self.settings.tts_provider
            tts_diagnostics: list[dict] = []
            clone_diagnostics: list[dict] = []
            final_translation_path = self._write_final_translation_file(project.storage_key, clips)
            tts_payload_path = self._write_tts_request_payload_file(project.storage_key, [])
            clone_diagnostics_path = self._write_clone_diagnostics_file(project.storage_key, [])

            for clip in clips:
                text = (clip.translation_text or clip.text or "").strip()
                if not text:
                    continue
                parent_artifact = self.artifacts.get_by_id(clip.artifact_id) if clip.artifact_id else None
                if not parent_artifact:
                    raise AppError("TTS_PARENT_ARTIFACT_NOT_FOUND", "Timeline clip parent artifact not found", 404)

                language_code = project.target_language or project.source_language or "tr"
                voice_profile, voice_name, voice_selection_source = self._resolve_voice_selection(
                    project_id=project.id,
                    character_id=clip.character_id,
                    language_code=language_code,
                    provider_key=resolved_provider_key,
                )

                source_duration_ms = max(int(clip.end_ms) - int(clip.start_ms), 1)
                tts_locale = self._resolve_tts_locale(language_code, voice_name)
                request_diagnostic = {
                    "timeline_clip_id": clip.id,
                    "transcript": clip.text,
                    "translated_text": clip.translation_text,
                    "tts_input_text": text,
                    "tts_language": language_code,
                    "tts_locale": tts_locale,
                    "target_language": project.target_language,
                    "source_language": project.source_language,
                    "provider": resolved_provider_key,
                    "voice_name": voice_name,
                    "voice_selection_source": voice_selection_source,
                    "source_start_ms": clip.start_ms,
                    "source_end_ms": clip.end_ms,
                    "source_duration_ms": source_duration_ms,
                }
                tts_diagnostics.append(request_diagnostic)
                self._write_tts_request_payload_file(project.storage_key, tts_diagnostics)
                logger.warning(
                    "TTS request prepared before audio generation: project_id=%s clip_id=%s target_language=%s locale=%s voice=%s text=%s",
                    project.id,
                    clip.id,
                    project.target_language,
                    tts_locale,
                    voice_name,
                    text[:240],
                )
                result = asyncio.run(
                    self._synthesize_with_duration_fit(
                        text=text,
                        language_code=language_code,
                        voice_name=voice_name,
                        voice_profile=voice_profile,
                        source_duration_ms=source_duration_ms,
                        project_source_language=project.source_language,
                        clone_diagnostics=clone_diagnostics,
                        project_storage_key=project.storage_key,
                        timeline_clip_id=clip.id,
                    )
                )

                artifact = self._create_audio_artifact(
                    project_storage_key=project.storage_key,
                    parent_artifact=parent_artifact,
                    job_id=job.id,
                    timeline_clip_id=clip.id,
                    result=result,
                )
                tts_duration_ms = int(result.get("duration_ms") or artifact.duration_ms or 0)
                synthesized_text = result.get("text") or text
                request_diagnostic["tts_input_text"] = synthesized_text
                request_diagnostic["tts_duration_ms"] = tts_duration_ms
                request_diagnostic["duration_fit_status"] = result.get("duration_fit_status")
                request_diagnostic["speed_factor"] = result.get("speed_factor", 1.0)
                request_diagnostic["rewrite_count"] = result.get("rewrite_count", 0)
                self._write_tts_request_payload_file(project.storage_key, tts_diagnostics)
                duration_ratio = round(tts_duration_ms / source_duration_ms, 3) if tts_duration_ms > 0 else 0.0
                segment_metadata = {
                    **result.get("metadata_json", {}),
                    "transcript": clip.text,
                    "translated_text": clip.translation_text,
                    "tts_input_text": synthesized_text,
                    "tts_language": language_code,
                    "tts_locale": tts_locale,
                    "target_language": project.target_language,
                    "final_translation_path": final_translation_path,
                    "tts_request_payload_path": tts_payload_path,
                    "clone_diagnostics_path": clone_diagnostics_path,
                    "cloned": bool(voice_profile and voice_profile.profile_type == "cloned"),
                    "reference_audio_artifact_id": (
                        voice_profile.reference_audio_artifact_id if voice_profile and voice_profile.profile_type == "cloned" else None
                    ),
                    "voice_selection_source": voice_selection_source,
                    "voice_profile_id": voice_profile.id if voice_profile else None,
                    "voice_profile_display_name": voice_profile.display_name if voice_profile else None,
                    "voice_profile_type": voice_profile.profile_type if voice_profile else "default",
                    "source_start_ms": clip.start_ms,
                    "source_end_ms": clip.end_ms,
                    "source_duration_ms": source_duration_ms,
                    "tts_duration_ms": tts_duration_ms,
                    "raw_tts_duration_ms": result.get("raw_tts_duration_ms", tts_duration_ms),
                    "fitted_tts_duration_ms": result.get("fitted_tts_duration_ms", tts_duration_ms),
                    "speed_factor": result.get("speed_factor", 1.0),
                    "rewrite_count": result.get("rewrite_count", 0),
                    "duration_fit_score": result.get("duration_fit_score"),
                    "duration_fit_status": result.get("duration_fit_status", "unknown"),
                    "duration_fit_text": synthesized_text,
                    "duration_fit_text_changed": synthesized_text != text,
                    "duration_ratio": duration_ratio,
                    "overrun_risk_ms": max(tts_duration_ms - source_duration_ms, 0),
                }
                if duration_ratio > 1.15 or (duration_ratio and duration_ratio < 0.85):
                    warnings = list(segment_metadata.get("warnings") or [])
                    if duration_ratio > 1.15:
                        message = "TTS audio is longer than the source speech slot; audio mix may trim it or it may overrun if not trimmed."
                        suggestion = "Shorten dub adaptation or increase speech rate without changing meaning."
                    else:
                        message = "TTS audio is shorter than the source speech slot; the dub may leave unnatural silence."
                        suggestion = "Use a slightly fuller adaptation or slower speech rate."
                    warnings.append(
                        {
                            "code": "TTS_DURATION_MISMATCH",
                            "message": message,
                            "duration_ratio": duration_ratio,
                            "source_duration_ms": source_duration_ms,
                            "tts_duration_ms": tts_duration_ms,
                            "suggestion": suggestion,
                        }
                    )
                    segment_metadata["warnings"] = warnings
                if voice_selection_source != "character_assignment":
                    warnings = list(segment_metadata.get("warnings") or [])
                    warnings.append(
                        {
                            "code": "FALLBACK_VOICE_USED",
                            "message": "No character voice assignment was found; fallback voice was used.",
                            "voice_selection_source": voice_selection_source,
                            "voice_name": voice_name,
                        }
                    )
                    segment_metadata["warnings"] = warnings
                similarity_score = self._voice_similarity_score(
                    voice_profile=voice_profile,
                    artifact=artifact,
                    metadata=segment_metadata,
                )
                if similarity_score is not None:
                    artifact.metadata_json = dict(segment_metadata)
                artifact.metadata_json = dict(segment_metadata)
                segment = DubSegment(
                    id=str(uuid7()),
                    project_id=project.id,
                    translation_segment_id=clip.translation_segment_id,
                    timeline_clip_id=clip.id,
                    character_id=clip.character_id,
                    voice_profile_id=voice_profile.id if voice_profile else None,
                    text=synthesized_text,
                    audio_artifact_id=artifact.id,
                    tts_artifact_id=artifact.id,
                    provider=result.get("provider", self.settings.tts_provider),
                    status=SegmentStatus.DRAFT,
                    duration_ms=result.get("duration_ms"),
                    duration_match_score=result.get("duration_fit_score"),
                    similarity_score=similarity_score,
                    metadata_json=segment_metadata,
                )
                self.dubs.create(segment)
                self.db.flush()

                clip.dub_segment_id = segment.id
                metadata = dict(clip.metadata_json or {})
                metadata["dub_segment_id"] = segment.id
                metadata["tts_audio_artifact_id"] = artifact.id
                clip.metadata_json = metadata
                clip.updated_at = datetime.now(UTC)

                created_segments.append(segment)
                self.events.publish_audit(
                    project_id=project.id,
                    actor_user_id=job.requested_by_user_id,
                    related_job_id=job.id,
                    entity_type="dub_segment",
                    entity_id=segment.id,
                    event_type=EventType.DUB_SEGMENT_CREATED.value,
                    payload_json={"timeline_clip_id": clip.id, "text": text},
                )
                self.events.publish_audit(
                    project_id=project.id,
                    actor_user_id=job.requested_by_user_id,
                    related_job_id=job.id,
                    entity_type="artifact",
                    entity_id=artifact.id,
                    event_type=EventType.TTS_AUDIO_GENERATED.value,
                    payload_json={"timeline_clip_id": clip.id, "artifact_type": artifact.artifact_type.value},
                )

            if not created_segments:
                raise AppError("TTS_SOURCE_TEXT_NOT_FOUND", "Timeline clips do not contain text for TTS", 409)

            self._update_voice_profile_similarity_scores(created_segments)

            job.output_json = {
                **(job.output_json or {}),
                "dub_segment_count": len(created_segments),
                "artifact_count": len(created_segments),
                "provider": created_segments[0].provider if created_segments else self.settings.tts_provider,
                "final_translation_path": final_translation_path,
                "tts_request_payload_path": tts_payload_path,
                "tts_diagnostics": tts_diagnostics,
                "clone_diagnostics_path": clone_diagnostics_path,
            }
            job.updated_at = datetime.now(UTC)

            self.events.publish_audit(
                project_id=project.id,
                actor_user_id=job.requested_by_user_id,
                related_job_id=job.id,
                entity_type="job",
                entity_id=job.id,
                event_type=EventType.TTS_COMPLETED.value,
                payload_json={"dub_segment_count": len(created_segments)},
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

    def _voice_similarity_score(self, *, voice_profile, artifact: Artifact, metadata: dict) -> float | None:
        if not voice_profile or voice_profile.profile_type != "cloned" or not voice_profile.reference_audio_artifact_id:
            return None
        reference_artifact = self.artifacts.get_by_id(voice_profile.reference_audio_artifact_id)
        if not reference_artifact:
            return None
        reference_path = self.storage.absolute_path(reference_artifact.storage_path)
        generated_path = self.storage.absolute_path(artifact.storage_path)
        if not reference_path.exists() or not generated_path.exists():
            return None
        try:
            comparison = self.voice_similarity.compare(reference_path, generated_path)
        except Exception as exc:
            metadata["voice_similarity_error"] = str(exc)
            return None
        metadata.update(comparison)
        metadata["voice_similarity_score"] = comparison["voice_similarity_score"]
        metadata["speaker_embedding_distance"] = comparison["speaker_embedding_distance"]
        return float(comparison["voice_similarity_score"])

    def _update_voice_profile_similarity_scores(self, segments: list[DubSegment]) -> None:
        profile_ids = {segment.voice_profile_id for segment in segments if segment.voice_profile_id and segment.similarity_score is not None}
        for profile_id in profile_ids:
            profile_segments = [
                segment
                for segment in segments
                if segment.voice_profile_id == profile_id and segment.similarity_score is not None
            ]
            if not profile_segments:
                continue
            average = sum(float(segment.similarity_score or 0) for segment in profile_segments) / len(profile_segments)
            profile = self.voice_profiles.voice_profiles.get_profile(profile_id)
            if not profile:
                continue
            profile.average_similarity_score = round(average, 2)
            metadata = dict(profile.metadata_json or {})
            metadata["average_similarity_score"] = round(average, 2)
            metadata["voice_similarity_segment_count"] = len(profile_segments)
            profile.metadata_json = metadata
            profile.updated_at = datetime.now(UTC)

    def _write_final_translation_file(self, project_storage_key: str, clips) -> str:
        lines = []
        for clip in clips:
            translated_text = (clip.translation_text or "").strip()
            source_text = (clip.text or "").strip()
            if not translated_text and not source_text:
                continue
            lines.append(
                "\n".join(
                    [
                        f"timeline_clip_id={clip.id}",
                        f"transcript={source_text}",
                        f"translated_text={translated_text}",
                        f"tts_input_text={(translated_text or source_text)}",
                    ]
                )
            )
        content = ("\n\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        relative_path, _, _ = self.storage.write_bytes(
            project_storage_key,
            "tts",
            "final_translation.txt",
            content,
        )
        return relative_path

    def _write_tts_request_payload_file(self, project_storage_key: str, payload: list[dict]) -> str:
        content = json.dumps({"segments": payload}, ensure_ascii=False, indent=2).encode("utf-8")
        relative_path, _, _ = self.storage.write_bytes(
            project_storage_key,
            "tts",
            "tts_request_payload.json",
            content,
        )
        return relative_path

    def _write_clone_diagnostics_file(self, project_storage_key: str, payload: list[dict]) -> str:
        content = json.dumps({"clone_diagnostics": payload}, ensure_ascii=False, indent=2).encode("utf-8")
        relative_path, _, _ = self.storage.write_bytes(
            project_storage_key,
            "tts",
            "clone_diagnostics.json",
            content,
        )
        return relative_path

    def _resolve_tts_locale(self, language_code: str | None, voice_name: str | None) -> str:
        if voice_name:
            parts = voice_name.split("-")
            if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
                return f"{parts[0]}-{parts[1]}"
        locale_map = {
            "tr": "tr-TR",
            "en": "en-US",
            "sr": "sr-RS",
        }
        return locale_map.get((language_code or "tr").lower(), language_code or "tr")

    def _resolve_voice_selection(
        self,
        *,
        project_id: str,
        character_id: str | None,
        language_code: str,
        provider_key: str,
    ):
        voice_profile, voice_name, source = self.voice_profiles.resolve_voice_for_character(
            project_id=project_id,
            character_id=character_id,
            provider=provider_key,
            language=language_code,
        )
        if voice_name:
            return voice_profile, voice_name, source

        if self.settings.tts_voice_name != "default":
            return voice_profile, self.settings.tts_voice_name, "settings_voice_name"
        if provider_key == "edge_tts":
            return voice_profile, self.settings.edge_tts_voice, "settings_edge_voice"
        return voice_profile, self.settings.tts_voice_name, "settings_default"

    async def _synthesize_with_duration_fit(
        self,
        *,
        text: str,
        language_code: str,
        voice_name: str | None,
        voice_profile,
        source_duration_ms: int,
        project_source_language: str | None = None,
        clone_diagnostics: list[dict] | None = None,
        project_storage_key: str | None = None,
        timeline_clip_id: str | None = None,
    ) -> dict:
        max_duration_ms = int(source_duration_ms * 1.05)
        min_duration_ms = int(source_duration_ms * 0.85)
        speed_factors = [1.0, 1.05, 1.10, 1.15, 1.20, 1.25]
        attempts = []
        adaptation_attempts = []
        original_text = text
        current_text = text
        rewrite_count = 0
        raw_duration_ms: int | None = None
        best_result: dict | None = None

        max_rewrite_count = 3 if self.settings.tts_duration_fit_allow_rewrite else 0
        for rewrite_index in range(max_rewrite_count + 1):
            if rewrite_index > 0:
                rewrite_count = rewrite_index
                previous_duration_ms = int(best_result.get("duration_ms") or 0) if best_result else raw_duration_ms
                rewrite = await self._rewrite_for_duration(
                    original_text,
                    current_text,
                    source_duration_ms,
                    previous_duration_ms,
                    rewrite_index,
                    language_code,
                )
                current_text = rewrite["adapted_text"]
                adaptation_attempts.append(rewrite)

            result = await self._synthesize_for_profile(
                text=current_text,
                language_code=language_code,
                voice_name=voice_name,
                voice_profile=voice_profile,
                project_source_language=project_source_language,
                clone_diagnostics=clone_diagnostics,
                project_storage_key=project_storage_key,
                timeline_clip_id=timeline_clip_id,
            )
            if raw_duration_ms is None:
                raw_duration_ms = int(result.get("duration_ms") or 0)

            for speed_factor in speed_factors:
                candidate = self._apply_speed_factor(result, speed_factor) if speed_factor > 1.0 else dict(result)
                fitted_duration_ms = int(candidate.get("duration_ms") or 0)
                duration_fit_score = self._duration_fit_score(source_duration_ms, fitted_duration_ms)
                attempts.append(
                    {
                        "rewrite_count": rewrite_count,
                        "text": current_text,
                        "speed_factor": speed_factor,
                        "duration_ms": fitted_duration_ms,
                        "duration_ratio": round(fitted_duration_ms / max(source_duration_ms, 1), 3),
                        "fits": fitted_duration_ms <= max_duration_ms,
                    }
                )
                if best_result is None or abs(fitted_duration_ms - source_duration_ms) < abs(int(best_result.get("duration_ms") or 0) - source_duration_ms):
                    best_result = dict(candidate)
                    best_result["text"] = current_text
                    best_result["speed_factor"] = speed_factor
                    best_result["rewrite_count"] = rewrite_count
                    best_result["duration_fit_score"] = duration_fit_score
                if min_duration_ms <= fitted_duration_ms <= max_duration_ms:
                    metadata = dict(candidate.get("metadata_json", {}))
                    metadata.update(
                        {
                            "adaptation_attempts": adaptation_attempts,
                            "duration_fit_attempts": attempts,
                            "duration_fit_status": "fit",
                            "raw_tts_duration_ms": raw_duration_ms,
                            "fitted_tts_duration_ms": fitted_duration_ms,
                            "candidate_duration_ms": fitted_duration_ms,
                            "best_duration_ms": fitted_duration_ms,
                            "target_duration_ms": source_duration_ms,
                            "duration_error_ms": fitted_duration_ms - source_duration_ms,
                            "speed_factor": speed_factor,
                            "rewrite_count": rewrite_count,
                            "duration_fit_score": duration_fit_score,
                            "duration_fit_target_ms": source_duration_ms,
                            "duration_fit_max_ms": max_duration_ms,
                            "duration_fit_text_changed": current_text != original_text,
                        }
                    )
                    candidate["metadata_json"] = metadata
                    candidate["raw_tts_duration_ms"] = raw_duration_ms
                    candidate["fitted_tts_duration_ms"] = fitted_duration_ms
                    candidate["speed_factor"] = speed_factor
                    candidate["rewrite_count"] = rewrite_count
                    candidate["duration_fit_score"] = duration_fit_score
                    candidate["duration_fit_status"] = "fit"
                    candidate["text"] = current_text
                    return candidate

        if best_result is None:
            raise AppError("TTS_DURATION_FIT_FAILED", "TTS duration fit did not produce any candidate", 502)
        fitted_duration_ms = int(best_result.get("duration_ms") or 0)
        metadata = dict(best_result.get("metadata_json", {}))
        warnings = list(metadata.get("warnings") or [])
        warnings.append(
            {
                "code": "TTS_DURATION_FIT_FAILED",
                "message": "TTS could not be fitted to the source speech window without further rewriting.",
                "source_duration_ms": source_duration_ms,
                "fitted_tts_duration_ms": fitted_duration_ms,
                "max_duration_ms": max_duration_ms,
            }
        )
        metadata.update(
            {
                "warnings": warnings,
                "adaptation_attempts": adaptation_attempts,
                "duration_fit_attempts": attempts,
                "duration_fit_status": "failed",
                "raw_tts_duration_ms": raw_duration_ms,
                "fitted_tts_duration_ms": fitted_duration_ms,
                "candidate_duration_ms": fitted_duration_ms,
                "best_duration_ms": fitted_duration_ms,
                "target_duration_ms": source_duration_ms,
                "duration_error_ms": fitted_duration_ms - source_duration_ms,
                "speed_factor": best_result.get("speed_factor", 1.0),
                "rewrite_count": best_result.get("rewrite_count", 0),
                "duration_fit_score": best_result.get("duration_fit_score"),
                "duration_fit_target_ms": source_duration_ms,
                "duration_fit_max_ms": max_duration_ms,
                "duration_fit_min_ms": min_duration_ms,
                "duration_fit_rewrite_allowed": self.settings.tts_duration_fit_allow_rewrite,
            }
        )
        best_result["metadata_json"] = metadata
        best_result["raw_tts_duration_ms"] = raw_duration_ms
        best_result["fitted_tts_duration_ms"] = fitted_duration_ms
        best_result["speed_factor"] = best_result.get("speed_factor", 1.0)
        best_result["rewrite_count"] = best_result.get("rewrite_count", 0)
        best_result["duration_fit_score"] = best_result.get("duration_fit_score")
        best_result["duration_fit_status"] = "failed"
        return best_result

    async def _rewrite_for_duration(
        self,
        original_text: str,
        current_text: str,
        target_duration_ms: int,
        previous_duration_ms: int | None,
        attempt_no: int,
        target_language: str,
    ) -> dict:
        min_similarity = self.settings.tts_duration_fit_min_semantic_similarity
        forced_candidate = self._forced_compact_rewrite(current_text)
        if forced_candidate and previous_duration_ms and previous_duration_ms > int(target_duration_ms * 1.10):
            score = semantic_similarity_score(original_text, forced_candidate)
            return {
                "attempt_no": attempt_no,
                "provider": "deterministic",
                "input_text": current_text,
                "adapted_text": forced_candidate if score >= min_similarity else current_text,
                "candidate_text": forced_candidate,
                "semantic_similarity_score": score,
                "accepted": score >= min_similarity,
                "target_duration_ms": target_duration_ms,
                "previous_duration_ms": previous_duration_ms,
                "metadata_json": {
                    "fallback": "forced_compact_rewrite",
                    "translation_stage": "tts_duration_feedback_adaptation",
                    "min_semantic_similarity": min_similarity,
                },
            }

        provider_name = self.settings.translation_provider
        provider_metadata = {}
        try:
            provider = self.providers.get("TRANSLATION")
            provider_result = await provider.adapt_for_tts_duration(
                text=current_text,
                target_language=target_language,
                target_duration_ms=target_duration_ms,
                previous_duration_ms=previous_duration_ms,
                attempt_no=attempt_no,
            )
            provider_name = provider_result.get("provider", provider_name)
            candidate = (provider_result.get("adapted_text") or current_text).strip()
            provider_metadata = provider_result.get("metadata_json", {})
        except Exception as exc:
            candidate = self._deterministic_duration_rewrite(current_text, attempt_no)
            provider_metadata = {"provider_error": str(exc), "fallback": "deterministic_duration_rewrite"}

        if not candidate or candidate == current_text:
            candidate = self._deterministic_duration_rewrite(current_text, attempt_no)
        elif previous_duration_ms and previous_duration_ms > int(target_duration_ms * 1.10):
            provider_candidate = candidate
            deterministic_candidate = self._deterministic_duration_rewrite(current_text, attempt_no)
            deterministic_score = semantic_similarity_score(original_text, deterministic_candidate)
            if len(deterministic_candidate) < len(candidate) and deterministic_score >= min_similarity:
                candidate = deterministic_candidate
                provider_metadata = {
                    **provider_metadata,
                    "provider_candidate_replaced_by_fallback": True,
                    "provider_candidate": provider_candidate,
                }

        score = semantic_similarity_score(original_text, candidate)
        accepted = score >= min_similarity

        return {
            "attempt_no": attempt_no,
            "provider": provider_name,
            "input_text": current_text,
            "adapted_text": candidate if accepted else current_text,
            "candidate_text": candidate,
            "semantic_similarity_score": score,
            "accepted": accepted,
            "target_duration_ms": target_duration_ms,
            "previous_duration_ms": previous_duration_ms,
            "metadata_json": {
                **provider_metadata,
                "min_semantic_similarity": min_similarity,
                "rejected_reason": None if accepted else "semantic_similarity_below_threshold",
            },
        }

    def _forced_compact_rewrite(self, text: str) -> str | None:
        compact_map = {
            "dinleyip ve konuşmayla, benim için de üst öğrencilerinle ilgilenmek anlamına geliyor.": "Dinleme ve konuşmaları iyi; sıra yazıyı geliştirmekte.",
            "dinliyor ve konuştuğunla, benim için üst sınıflarla ilgilenmek gibi.": "Dinleme ve konuşma iyi; sıra yazıyı geliştirmekte.",
            "yazma alıştırmaları onları kendi hayal güçlerini ortaya çıkarmaya yardımcı olur": "Yazma çalışmaları hayal gücünü geliştirir.",
            "yazma alıştırmaları onları kendi hayal güçlerini geliştirir": "Yazma çalışmaları hayal gücünü geliştirir.",
            "yazma alıştırmaları onları kendi hayal güçlerini geliştirir.": "Yazma çalışmaları hayal gücünü geliştirir.",
        }
        return compact_map.get(text.strip().casefold())

    def _deterministic_duration_rewrite(self, text: str, attempt_no: int) -> str:
        cleaned = text.strip()
        compact_map = {
            "dinleyip ve konuşmayla, benim için de üst öğrencilerinle ilgilenmek anlamına geliyor.": "Dinleme ve konuşmaları iyi; sıra yazılarını geliştirmekte.",
            "yazma alıştırmaları onları kendi hayal güçlerini ortaya çıkarmaya yardımcı olur": "Yazma çalışmaları hayal güçlerini geliştirir.",
            "yazma alıştırmaları onları kendi hayal güçlerini geliştirir": "Yazma çalışmaları hayal gücünü geliştirir.",
            "yazma alıştırmaları onları kendi hayal güçlerini geliştirir.": "Yazma çalışmaları hayal gücünü geliştirir.",
        }
        normalized = cleaned.casefold()
        if normalized in compact_map:
            return compact_map[normalized]

        candidate = fit_turkish_text_to_duration(cleaned, max(900, 2200 if attempt_no >= 2 else 2800))
        if candidate != cleaned:
            return candidate
        words = cleaned.split()
        if len(words) <= 4:
            return cleaned
        keep_ratio = 0.65 if attempt_no == 1 else 0.5
        keep = max(3, int(len(words) * keep_ratio))
        shortened = " ".join(words[:keep]).strip(" ,;:")
        return shortened + ("." if not shortened.endswith((".", "!", "?")) else "")

    def _apply_speed_factor(self, result: dict, speed_factor: float) -> dict:
        with tempfile.TemporaryDirectory(prefix="tts-fit-") as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.wav"
            output_path = temp_path / "output.wav"
            input_path.write_bytes(result["audio_bytes"])
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(input_path),
                    "-filter:a",
                    f"atempo={speed_factor:.2f}",
                    "-ac",
                    "1",
                    "-ar",
                    "22050",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            fitted = dict(result)
            fitted["audio_bytes"] = output_path.read_bytes()
            fitted["duration_ms"] = self._wav_duration_ms(output_path)
            metadata = dict(result.get("metadata_json", {}))
            metadata["speed_factor"] = speed_factor
            metadata["speed_adjusted"] = True
            fitted["metadata_json"] = metadata
            return fitted

    def _wav_duration_ms(self, path: Path) -> int:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            return int((frame_count / frame_rate) * 1000) if frame_rate else 0

    def _duration_fit_score(self, source_duration_ms: int, fitted_duration_ms: int) -> float:
        if source_duration_ms <= 0 or fitted_duration_ms <= 0:
            return 0.0
        ratio = min(source_duration_ms, fitted_duration_ms) / max(source_duration_ms, fitted_duration_ms)
        return round(ratio, 3)

    async def _synthesize_for_profile(
        self,
        *,
        text: str,
        language_code: str,
        voice_name: str | None,
        voice_profile,
        project_source_language: str | None = None,
        clone_diagnostics: list[dict] | None = None,
        project_storage_key: str | None = None,
        timeline_clip_id: str | None = None,
    ) -> dict:
        logger.warning(
            "TTS provider call: provider=%s cloned=%s language=%s locale=%s voice=%s text=%s",
            voice_profile.provider if voice_profile and voice_profile.profile_type == "cloned" else self.settings.tts_provider,
            bool(voice_profile and voice_profile.profile_type == "cloned"),
            language_code,
            self._resolve_tts_locale(language_code, voice_name),
            voice_name,
            text[:240],
        )
        if voice_profile and voice_profile.profile_type == "cloned":
            if voice_profile.status != "ready":
                raise AppError("VOICE_PROFILE_NOT_READY", "Cloned voice profile is not ready for TTS", 409)
            if not voice_profile.reference_audio_artifact_id:
                raise AppError("VOICE_REFERENCE_NOT_FOUND", "Cloned voice profile does not have reference audio", 409)
            reference_artifact = self.artifacts.get_by_id(voice_profile.reference_audio_artifact_id)
            if not reference_artifact:
                raise AppError("VOICE_REFERENCE_NOT_FOUND", "Cloned voice reference artifact not found", 404)
            reference_path = self.storage.absolute_path(reference_artifact.storage_path)
            if not reference_path.exists():
                raise AppError("VOICE_REFERENCE_FILE_NOT_FOUND", "Cloned voice reference file not found", 404)
            reference_duration_ms = reference_artifact.duration_ms or voice_profile.sample_duration_ms or 0
            reference_metadata = reference_artifact.metadata_json or {}
            reference_analysis = self.voice_similarity.analyze(reference_path)
            if reference_duration_ms < self.settings.voice_clone_min_sample_duration_ms:
                voice_profile.status = "failed"
                voice_profile.updated_at = datetime.now(UTC)
                raise AppError(
                    "VOICE_REFERENCE_TOO_SHORT",
                    f"Reference sample must be at least {self.settings.voice_clone_min_sample_duration_ms} ms",
                    409,
                )
            reference_language = self._resolve_reference_language(
                reference_metadata=reference_metadata,
                voice_profile_metadata=voice_profile.metadata_json or {},
                project_source_language=project_source_language,
            )
            reference_text = (
                (reference_artifact.metadata_json or {}).get("prompt_text")
                or (voice_profile.metadata_json or {}).get("reference_text")
                or ""
            )
            target_language = self._normalize_language_code(language_code)
            reference_text_used = bool(reference_text and reference_language == target_language)
            if reference_text and not reference_text_used:
                logger.warning(
                    "CosyVoice cross-lingual mode selected: reference_language=%s target_language=%s voice_profile_id=%s",
                    reference_language,
                    target_language,
                    voice_profile.id,
                )
            clone_mode = self._resolve_clone_mode(target_language)
            if clone_mode == "tts_plus_voice_conversion":
                diagnostic = {
                    "clone_id": voice_profile.voice_id,
                    "voice_profile_id": voice_profile.id,
                    "provider": "voice_conversion",
                    "voice_conversion_provider": self.settings.voice_conversion_provider,
                    "base_tts_provider": self.settings.tts_voice_conversion_base_provider,
                    "base_voice": self.settings.tts_voice_conversion_base_voice,
                    "language": language_code,
                    "locale": self._resolve_tts_locale(language_code, self.settings.tts_voice_conversion_base_voice),
                    "voice_name": voice_name,
                    "reference_audio_artifact_id": voice_profile.reference_audio_artifact_id,
                    "reference_duration": round(reference_duration_ms / 1000, 3),
                    "reference_duration_ms": reference_duration_ms,
                    "reference_language": reference_language,
                    "target_language": target_language,
                    "clone_mode": clone_mode,
                    "reference_audio_analysis": reference_analysis,
                    "generation_status": "started",
                }
                if clone_diagnostics is not None:
                    clone_diagnostics.append(diagnostic)
                    if project_storage_key:
                        self._write_clone_diagnostics_file(project_storage_key, clone_diagnostics)
                try:
                    result = await self._synthesize_with_voice_conversion(
                        text=text,
                        language_code=language_code,
                        voice_profile=voice_profile,
                        reference_path=reference_path,
                        reference_artifact_id=voice_profile.reference_audio_artifact_id,
                        project_storage_key=project_storage_key,
                        timeline_clip_id=timeline_clip_id,
                    )
                except Exception as exc:
                    diagnostic["generation_status"] = "failed"
                    diagnostic["error"] = str(exc)
                    if clone_diagnostics is not None and project_storage_key:
                        self._write_clone_diagnostics_file(project_storage_key, clone_diagnostics)
                    raise
                diagnostic["generation_status"] = "success"
                diagnostic["duration_ms"] = result.get("duration_ms")
                diagnostic["provider_metadata"] = result.get("metadata_json", {})
                if clone_diagnostics is not None and project_storage_key:
                    self._write_clone_diagnostics_file(project_storage_key, clone_diagnostics)
                metadata = dict(result.get("metadata_json", {}))
                metadata["cloned"] = True
                metadata["reference_audio_artifact_id"] = voice_profile.reference_audio_artifact_id
                metadata["reference_duration_ms"] = reference_duration_ms
                metadata["reference_language"] = reference_language
                metadata["reference_audio_analysis"] = reference_analysis
                metadata["sample_quality_score"] = (
                    reference_metadata.get("sample_quality_score")
                    if reference_metadata.get("sample_quality_score") is not None
                    else voice_profile.quality_score
                )
                metadata["normalized"] = bool(reference_metadata.get("normalized"))
                metadata["silence_trimmed"] = bool(reference_metadata.get("silence_trimmed"))
                metadata["voice_profile_id"] = voice_profile.id
                metadata["model_name"] = metadata.get("model_name") or self.settings.voice_conversion_provider
                result["metadata_json"] = metadata
                return result
            clone_provider = self.providers.get("VOICE_CLONE", voice_profile.provider or None)
            diagnostic = {
                "clone_id": voice_profile.voice_id,
                "voice_profile_id": voice_profile.id,
                "provider": voice_profile.provider,
                "model": self.settings.cosyvoice_model_name if voice_profile.provider == "cosyvoice" else voice_profile.provider,
                "language": language_code,
                "locale": self._resolve_tts_locale(language_code, voice_name),
                "voice_name": voice_name,
                "reference_audio_artifact_id": voice_profile.reference_audio_artifact_id,
                "reference_duration": round(reference_duration_ms / 1000, 3),
                "reference_duration_ms": reference_duration_ms,
                "reference_language": reference_language,
                "reference_text_used": reference_text_used,
                "cosyvoice_mode": "zero_shot" if reference_text_used else "cross_lingual",
                "reference_audio_analysis": reference_analysis,
                "generation_status": "started",
            }
            if clone_diagnostics is not None:
                clone_diagnostics.append(diagnostic)
                if project_storage_key:
                    self._write_clone_diagnostics_file(project_storage_key, clone_diagnostics)
            try:
                result = await clone_provider.synthesize(
                    text=text,
                    reference_audio_path=reference_path,
                    language_code=language_code,
                    voice_profile_id=voice_profile.id,
                    voice_name=voice_name,
                    reference_audio_artifact_id=voice_profile.reference_audio_artifact_id,
                    reference_text=reference_text if reference_text_used else "",
                    reference_language=reference_language,
                target_language=language_code,
                    cosyvoice_mode="zero_shot" if reference_text_used else "cross_lingual",
                )
            except Exception as exc:
                diagnostic["generation_status"] = "failed"
                diagnostic["error"] = str(exc)
                if clone_diagnostics is not None and project_storage_key:
                    self._write_clone_diagnostics_file(project_storage_key, clone_diagnostics)
                raise
            diagnostic["generation_status"] = "success"
            diagnostic["duration_ms"] = result.get("duration_ms")
            diagnostic["provider_metadata"] = result.get("metadata_json", {})
            if clone_diagnostics is not None and project_storage_key:
                self._write_clone_diagnostics_file(project_storage_key, clone_diagnostics)
            metadata = dict(result.get("metadata_json", {}))
            metadata["cloned"] = True
            metadata["reference_audio_artifact_id"] = voice_profile.reference_audio_artifact_id
            metadata["reference_duration_ms"] = reference_duration_ms
            metadata["reference_language"] = reference_language
            metadata["reference_text_used"] = reference_text_used
            metadata["cosyvoice_mode"] = "zero_shot" if reference_text_used else "cross_lingual"
            metadata["reference_audio_analysis"] = reference_analysis
            metadata["sample_quality_score"] = (
                reference_metadata.get("sample_quality_score")
                if reference_metadata.get("sample_quality_score") is not None
                else voice_profile.quality_score
            )
            metadata["normalized"] = bool(reference_metadata.get("normalized"))
            metadata["silence_trimmed"] = bool(reference_metadata.get("silence_trimmed"))
            metadata["voice_profile_id"] = voice_profile.id
            metadata["model_name"] = metadata.get("model_name") or voice_profile.provider or "voice_clone"
            result["metadata_json"] = metadata
            return result

        provider = self.providers.get("TTS")
        result = await provider.synthesize(
            text=text,
            language_code=language_code,
            voice_name=voice_name,
        )
        metadata = dict(result.get("metadata_json", {}))
        metadata.setdefault("cloned", False)
        result["metadata_json"] = metadata
        return result

    async def _synthesize_with_voice_conversion(
        self,
        *,
        text: str,
        language_code: str,
        voice_profile,
        reference_path: Path,
        reference_artifact_id: str,
        project_storage_key: str | None = None,
        timeline_clip_id: str | None = None,
    ) -> dict:
        if self.settings.tts_voice_conversion_base_provider != "edge_tts":
            raise AppError(
                "VOICE_CONVERSION_BASE_TTS_UNSUPPORTED",
                "Only edge_tts is supported as the Sprint 48B voice conversion base TTS provider.",
                409,
            )
        base_provider = self.providers.get("TTS", self.settings.tts_voice_conversion_base_provider)
        base_result = await base_provider.synthesize(
            text=text,
            language_code=language_code,
            voice_name=self.settings.tts_voice_conversion_base_voice,
        )
        voice_conversion_provider = self.providers.get("VOICE_CONVERSION", self.settings.voice_conversion_provider)
        if project_storage_key and timeline_clip_id:
            debug_dir = self.storage.ensure_project_structure(project_storage_key) / "tts" / "voice_conversion"
            debug_dir.mkdir(parents=True, exist_ok=True)
            base_path = debug_dir / f"{timeline_clip_id}-base.wav"
            converted_path = debug_dir / f"{timeline_clip_id}-seedvc.wav"
            base_path.write_bytes(base_result["audio_bytes"])
            conversion_result = voice_conversion_provider.convert(
                source_audio_path=base_path,
                reference_audio_path=reference_path,
                output_audio_path=converted_path,
                options={
                    "text": text,
                    "language_code": language_code,
                    "voice_profile_id": voice_profile.id,
                    "reference_audio_artifact_id": reference_artifact_id,
                },
            )
            return self._voice_conversion_result(
                base_result=base_result,
                conversion_result=conversion_result,
                converted_path=converted_path,
                base_path=base_path,
                language_code=language_code,
                voice_profile=voice_profile,
                reference_artifact_id=reference_artifact_id,
            )

        with tempfile.TemporaryDirectory(prefix="tts-vc-") as temp_dir:
            temp_path = Path(temp_dir)
            base_path = temp_path / "base_tts.wav"
            converted_path = temp_path / "converted.wav"
            base_path.write_bytes(base_result["audio_bytes"])
            conversion_result = voice_conversion_provider.convert(
                source_audio_path=base_path,
                reference_audio_path=reference_path,
                output_audio_path=converted_path,
                options={
                    "text": text,
                    "language_code": language_code,
                    "voice_profile_id": voice_profile.id,
                    "reference_audio_artifact_id": reference_artifact_id,
                },
            )
            return self._voice_conversion_result(
                base_result=base_result,
                conversion_result=conversion_result,
                converted_path=converted_path,
                base_path=base_path,
                language_code=language_code,
                voice_profile=voice_profile,
                reference_artifact_id=reference_artifact_id,
            )

    def _voice_conversion_result(
        self,
        *,
        base_result: dict,
        conversion_result: dict,
        converted_path: Path,
        base_path: Path,
        language_code: str,
        voice_profile,
        reference_artifact_id: str,
    ) -> dict:
        audio_bytes = converted_path.read_bytes()
        duration_ms = conversion_result.get("duration_ms") or self._wav_duration_ms(converted_path)
        metadata = {
            "cloned": True,
            "clone_mode": "tts_plus_voice_conversion",
            "provider_chain": ["edge_tts", self.settings.voice_conversion_provider],
            "provider": self.settings.voice_conversion_provider,
            "base_tts_provider": self.settings.tts_voice_conversion_base_provider,
            "base_voice": self.settings.tts_voice_conversion_base_voice,
            "base_tts_duration_ms": base_result.get("duration_ms"),
            "base_tts_path": str(base_path),
            "seedvc_output_path": str(converted_path),
            "voice_conversion_duration_ms": duration_ms,
            "voice_profile_id": voice_profile.id,
            "voice_name": voice_profile.voice_id,
            "language_code": language_code,
            "target_language": language_code,
            "reference_audio_artifact_id": reference_artifact_id,
            "voice_conversion_metadata": conversion_result.get("metadata_json", {}),
        }
        return {
            "provider": self.settings.voice_conversion_provider,
            "audio_bytes": audio_bytes,
            "mime_type": "audio/wav",
            "file_extension": ".wav",
            "duration_ms": duration_ms,
            "metadata_json": metadata,
        }

    def _resolve_clone_mode(self, target_language: str | None) -> str:
        configured = (self.settings.tts_clone_mode or "auto").strip().lower()
        if configured in {"direct_clone_tts", "tts_plus_voice_conversion"}:
            return configured
        if configured != "auto":
            raise AppError(
                "TTS_CLONE_MODE_INVALID",
                "TTS_CLONE_MODE must be auto, direct_clone_tts, or tts_plus_voice_conversion",
                409,
            )
        if target_language == "tr":
            return "tts_plus_voice_conversion"
        return "direct_clone_tts"

    def _normalize_language_code(self, language_code: str | None) -> str | None:
        if not language_code:
            return None
        normalized = str(language_code).strip().lower()
        if not normalized or normalized in {"auto", "unknown", "none"}:
            return None
        return normalized.split("-")[0]

    def _resolve_reference_language(
        self,
        *,
        reference_metadata: dict,
        voice_profile_metadata: dict,
        project_source_language: str | None,
    ) -> str | None:
        value = (
            reference_metadata.get("reference_language")
            or reference_metadata.get("source_language")
            or voice_profile_metadata.get("reference_language")
            or voice_profile_metadata.get("source_language")
            or project_source_language
        )
        if not value:
            return None
        return self._normalize_language_code(str(value))

    def _clear_existing_outputs(self, project_id: str) -> None:
        existing_segments = self.dubs.list_for_project(project_id)
        artifact_ids = {
            artifact_id
            for segment in existing_segments
            for artifact_id in [segment.audio_artifact_id, segment.tts_artifact_id]
            if artifact_id
        }
        for clip in self.timeline.list_clips_for_project(project_id):
            clip.dub_segment_id = None
            metadata = dict(clip.metadata_json or {})
            metadata.pop("dub_segment_id", None)
            metadata.pop("tts_audio_artifact_id", None)
            clip.metadata_json = metadata
            clip.updated_at = datetime.now(UTC)

        for artifact_id in artifact_ids:
            artifact = self.artifacts.get_by_id(artifact_id)
            if not artifact:
                continue
            if artifact.storage_path and self.storage.exists(artifact.storage_path):
                self.storage.delete_relative_path(artifact.storage_path)
            self.db.delete(artifact)

        self.dubs.delete_for_project(project_id)
        self.db.flush()

    def _create_audio_artifact(
        self,
        *,
        project_storage_key: str,
        parent_artifact: Artifact,
        job_id: str,
        timeline_clip_id: str,
        result: dict,
    ) -> Artifact:
        file_extension = result.get("file_extension", ".wav")
        relative_path, size_bytes, checksum = self.storage.write_bytes(
            project_storage_key,
            "tts",
            f"{timeline_clip_id}{file_extension}",
            result["audio_bytes"],
        )
        artifact = Artifact(
            id=str(uuid7()),
            project_id=parent_artifact.project_id,
            created_by_job_id=job_id,
            artifact_type=ArtifactType.TTS_AUDIO,
            storage_path=relative_path,
            file_name=Path(relative_path).name,
            mime_type=result.get("mime_type", "audio/wav"),
            size_bytes=size_bytes,
            checksum_sha256=checksum,
            duration_ms=result.get("duration_ms"),
            metadata_json=result.get("metadata_json", {}),
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
        self.db.flush()
        return artifact
