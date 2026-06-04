import io
import math
import struct
import wave
from pathlib import Path

from app.providers.voice_clone.base import VoiceCloneProvider


class MockVoiceCloneProvider(VoiceCloneProvider):
    async def synthesize(
        self,
        *,
        text: str,
        reference_audio_path: Path,
        language_code: str | None = None,
        voice_profile_id: str | None = None,
        **kwargs,
    ) -> dict:
        del kwargs
        duration_ms = max(300, min(7000, len((text or "").strip() or "mock clone") * 90))
        sample_rate = 22050
        frame_count = int(sample_rate * (duration_ms / 1000))
        buffer = io.BytesIO()
        amplitude = 16000
        checksum_seed = sum(reference_audio_path.read_bytes()[:512]) if reference_audio_path.exists() else 0
        frequency = 310.0 + (checksum_seed % 180)

        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            for index in range(frame_count):
                sample = int(amplitude * math.sin(2.0 * math.pi * frequency * (index / sample_rate)))
                wav_file.writeframesraw(struct.pack("<h", sample))

        return {
            "provider": "mock_voice_clone",
            "audio_bytes": buffer.getvalue(),
            "mime_type": "audio/wav",
            "file_extension": ".wav",
            "duration_ms": duration_ms,
            "metadata_json": {
                "voice_profile_id": voice_profile_id,
                "language_code": language_code or "tr",
                "reference_audio_path": str(reference_audio_path),
                "sample_rate": sample_rate,
                "character_count": len(text or ""),
            },
        }
