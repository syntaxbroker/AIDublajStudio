import json
import os
import subprocess
import time
import wave
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError
from app.providers.voice_conversion.base import VoiceConversionProvider


class SeedVCProvider(VoiceConversionProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    def convert(
        self,
        *,
        source_audio_path: Path,
        reference_audio_path: Path,
        output_audio_path: Path,
        options: dict | None = None,
    ) -> dict:
        options = options or {}
        if not source_audio_path.exists():
            raise AppError("VOICE_CONVERSION_SOURCE_MISSING", "Voice conversion source audio file not found", 404)
        if not reference_audio_path.exists():
            raise AppError("VOICE_CONVERSION_REFERENCE_MISSING", "Voice conversion reference audio file not found", 404)

        repo_dir = Path(options.get("repo_dir") or self.settings.seedvc_repo_dir or "")
        if not repo_dir.exists():
            raise AppError(
                "SEEDVC_RUNTIME_MISSING",
                "SeedVC runtime is not installed. Set SEEDVC_REPO_DIR to a local SeedVC checkout.",
                503,
            )

        inference_script = repo_dir / "inference.py"
        if not inference_script.exists():
            raise AppError("SEEDVC_INFERENCE_MISSING", f"SeedVC inference.py not found at {inference_script}", 503)

        output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        output_dir = output_audio_path.parent / f"{output_audio_path.stem}-seedvc-out"
        output_dir.mkdir(parents=True, exist_ok=True)

        command = [
            self.settings.seedvc_python_executable or "python",
            str(inference_script),
            "--source",
            str(source_audio_path),
            "--target",
            str(reference_audio_path),
            "--output",
            str(output_dir),
            "--diffusion-steps",
            str(options.get("diffusion_steps") or self.settings.seedvc_diffusion_steps),
            "--length-adjust",
            str(options.get("length_adjust") or self.settings.seedvc_length_adjust),
            "--inference-cfg-rate",
            str(options.get("inference_cfg_rate") or self.settings.seedvc_inference_cfg_rate),
            "--fp16",
            str(options.get("fp16") if options.get("fp16") is not None else self.settings.seedvc_fp16),
        ]
        if self.settings.seedvc_checkpoint:
            command.extend(["--checkpoint", self.settings.seedvc_checkpoint])
        if self.settings.seedvc_config:
            command.extend(["--config", self.settings.seedvc_config])

        started = time.perf_counter()
        env = os.environ.copy()
        if self.settings.seedvc_cuda_visible_devices:
            env["CUDA_VISIBLE_DEVICES"] = self.settings.seedvc_cuda_visible_devices

        try:
            completed = subprocess.run(
                command,
                cwd=str(repo_dir),
                check=True,
                capture_output=True,
                text=True,
                timeout=self.settings.seedvc_timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise AppError("SEEDVC_TIMEOUT", f"SeedVC conversion timed out after {self.settings.seedvc_timeout_seconds}s", 504) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise AppError("SEEDVC_CONVERSION_FAILED", detail or "SeedVC conversion failed", 502) from exc

        candidates = sorted(
            [*output_dir.rglob("*.wav"), *output_dir.rglob("*.flac"), *output_dir.rglob("*.mp3")],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise AppError("SEEDVC_OUTPUT_MISSING", "SeedVC did not produce an output audio file", 502)

        output_audio_path.write_bytes(candidates[0].read_bytes())
        duration_ms, sample_rate, channels = self._probe_wav(output_audio_path)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        metadata_path = output_audio_path.with_suffix(".seedvc.json")
        metadata = {
            "provider": "seedvc",
            "source_audio_path": str(source_audio_path),
            "reference_audio_path": str(reference_audio_path),
            "output_audio_path": str(output_audio_path),
            "seedvc_repo_dir": str(repo_dir),
            "command": command,
            "processing_time_ms": elapsed_ms,
            "duration_ms": duration_ms,
            "sample_rate": sample_rate,
            "channels": channels,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "provider": "seedvc",
            "audio_path": output_audio_path,
            "duration_ms": duration_ms,
            "sample_rate": sample_rate,
            "metadata_json": metadata,
        }

    def _probe_wav(self, path: Path) -> tuple[int, int, int]:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            channels = wav_file.getnchannels()
        duration_ms = int((frame_count / frame_rate) * 1000) if frame_rate else 0
        return duration_ms, frame_rate, channels
