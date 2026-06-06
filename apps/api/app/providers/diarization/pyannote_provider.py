import asyncio
import json
import math
import subprocess
import tempfile
import time
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError
from app.providers.diarization.base import DiarizationProvider


class PyannoteDiarizationProvider(DiarizationProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def diarize(self, source_path: str) -> dict:
        return await asyncio.to_thread(self._diarize_sync, source_path)

    def _diarize_sync(self, source_path: str) -> dict:
        if not self.settings.pyannote_auth_token:
            raise AppError("PYANNOTE_AUTH_TOKEN_MISSING", "Pyannote auth token is not configured", 500)

        import torch
        from pyannote.audio import Pipeline

        load_started = time.perf_counter()
        pipeline = Pipeline.from_pretrained(
            self.settings.pyannote_pipeline_name,
            token=self.settings.pyannote_auth_token,
        )
        model_load_time_ms = int((time.perf_counter() - load_started) * 1000)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda":
            pipeline.to(torch.device("cuda"))

        prepared = self._prepare_audio(source_path)
        inference_started = time.perf_counter()
        try:
            diarization = pipeline(str(prepared["path"]))
            inference_time_ms = int((time.perf_counter() - inference_started) * 1000)
            if not hasattr(diarization, "itertracks"):
                diarization = getattr(diarization, "speaker_diarization", diarization)

            source_duration_ms = int(prepared["source_duration_ms"])
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                start_ms = max(0, int(float(turn.start) * 1000))
                end_ms = min(source_duration_ms, int(float(turn.end) * 1000))
                if end_ms <= start_ms:
                    continue
                segments.append(
                    {
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "speaker_label": str(speaker),
                        "confidence": None,
                        "metadata_json": {
                            "source_audio_prepared": True,
                            "source_audio_padded_ms": prepared["pad_ms"],
                        },
                    }
                )
        finally:
            temp_dir = prepared.get("temp_dir")
            if temp_dir:
                temp_dir.cleanup()

        return {
            "provider": "pyannote",
            "segments": segments,
            "device": device,
            "model_load_time_ms": model_load_time_ms,
            "inference_time_ms": inference_time_ms,
            "source_duration_ms": prepared["source_duration_ms"],
            "prepared_duration_ms": prepared["prepared_duration_ms"],
            "source_audio_padded_ms": prepared["pad_ms"],
        }

    def _prepare_audio(self, source_path: str) -> dict:
        source_duration_seconds = self._probe_duration_seconds(source_path)
        if source_duration_seconds <= 0:
            raise AppError("DIARIZATION_SOURCE_DURATION_INVALID", "Source media duration could not be read", 422)

        chunk_seconds = 10
        prepared_duration_seconds = math.ceil(source_duration_seconds / chunk_seconds) * chunk_seconds
        pad_seconds = max(0.0, prepared_duration_seconds - source_duration_seconds)
        temp_dir = tempfile.TemporaryDirectory(prefix="pyannote-diarization-")
        prepared_path = Path(temp_dir.name) / "prepared.wav"
        audio_filter = f"apad=pad_dur={pad_seconds:.3f}" if pad_seconds > 0.001 else "anull"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            source_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            audio_filter,
            "-t",
            f"{prepared_duration_seconds:.3f}",
            str(prepared_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            temp_dir.cleanup()
            raise AppError(
                "DIARIZATION_AUDIO_PREP_FAILED",
                f"Failed to prepare audio for diarization: {result.stderr[-1000:]}",
                500,
            )
        return {
            "path": prepared_path,
            "temp_dir": temp_dir,
            "source_duration_ms": int(source_duration_seconds * 1000),
            "prepared_duration_ms": int(prepared_duration_seconds * 1000),
            "pad_ms": int(pad_seconds * 1000),
        }

    def _probe_duration_seconds(self, source_path: str) -> float:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            source_path,
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise AppError("DIARIZATION_SOURCE_PROBE_FAILED", result.stderr[-1000:] or "ffprobe failed", 500)
        try:
            payload = json.loads(result.stdout)
            return float(payload["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AppError("DIARIZATION_SOURCE_PROBE_FAILED", "ffprobe did not return a valid duration", 500) from exc
