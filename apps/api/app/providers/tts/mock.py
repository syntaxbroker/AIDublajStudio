import io
import math
import struct
import wave

from app.providers.tts.base import TTSProvider


class MockTTSProvider(TTSProvider):
    async def synthesize(
        self,
        *,
        text: str,
        language_code: str | None = None,
        voice_name: str | None = None,
        **kwargs,
    ) -> dict:
        del kwargs
        duration_ms = max(300, min(6000, len((text or "").strip() or "mock") * 90))
        sample_rate = 22050
        frame_count = int(sample_rate * (duration_ms / 1000))
        buffer = io.BytesIO()
        amplitude = 16000
        frequency = 440.0 if (language_code or "tr").startswith("tr") else 523.25

        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            for index in range(frame_count):
                sample = int(amplitude * math.sin(2.0 * math.pi * frequency * (index / sample_rate)))
                wav_file.writeframesraw(struct.pack("<h", sample))

        audio_bytes = buffer.getvalue()
        return {
            "provider": "mock",
            "audio_bytes": audio_bytes,
            "mime_type": "audio/wav",
            "file_extension": ".wav",
            "duration_ms": duration_ms,
            "metadata_json": {
                "voice_name": voice_name or "mock",
                "language_code": language_code or "auto",
                "sample_rate": sample_rate,
                "character_count": len(text or ""),
            },
        }
