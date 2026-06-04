import subprocess
import tempfile
import wave
from pathlib import Path

import edge_tts

from app.core.config import get_settings
from app.core.errors import AppError
from app.providers.tts.base import TTSProvider


class EdgeTTSProvider(TTSProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def synthesize(
        self,
        *,
        text: str,
        language_code: str | None = None,
        voice_name: str | None = None,
        **kwargs,
    ) -> dict:
        del kwargs
        resolved_text = (text or "").strip()
        if not resolved_text:
            raise AppError("TTS_TEXT_REQUIRED", "TTS text is required", 409)

        resolved_voice = voice_name if voice_name and voice_name != "default" else self.settings.edge_tts_voice

        with tempfile.TemporaryDirectory(prefix="edge-tts-") as temp_dir:
            temp_path = Path(temp_dir)
            mp3_path = temp_path / "tts.mp3"
            wav_path = temp_path / "tts.wav"

            try:
                communicator = edge_tts.Communicate(resolved_text, resolved_voice)
                await communicator.save(str(mp3_path))
            except Exception as exc:
                raise AppError("EDGE_TTS_SYNTHESIS_FAILED", f"Edge TTS synthesis failed: {exc}", 502) from exc

            if not mp3_path.exists():
                raise AppError("EDGE_TTS_OUTPUT_MISSING", "Edge TTS did not produce an audio file", 502)

            try:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(mp3_path),
                        "-ac",
                        "1",
                        "-ar",
                        "22050",
                        str(wav_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise AppError("EDGE_TTS_CONVERSION_FAILED", f"Edge TTS conversion failed: {exc.stderr.strip()}", 502) from exc

            if not wav_path.exists():
                raise AppError("EDGE_TTS_WAV_MISSING", "Edge TTS WAV conversion did not produce an output file", 502)

            with wave.open(str(wav_path), "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                duration_ms = int((frame_count / frame_rate) * 1000) if frame_rate else 0

            audio_bytes = wav_path.read_bytes()
            return {
                "provider": "edge_tts",
                "audio_bytes": audio_bytes,
                "mime_type": "audio/wav",
                "file_extension": ".wav",
                "duration_ms": duration_ms,
                "metadata_json": {
                    "voice_name": resolved_voice,
                    "language_code": language_code or "tr",
                    "sample_rate": 22050,
                    "source": "edge_tts",
                },
            }
