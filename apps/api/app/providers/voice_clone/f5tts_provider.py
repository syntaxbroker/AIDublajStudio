from pathlib import Path

from app.core.errors import AppError
from app.providers.voice_clone.base import VoiceCloneProvider


class F5TTSProvider(VoiceCloneProvider):
    async def synthesize(
        self,
        *,
        text: str,
        reference_audio_path: Path,
        language_code: str | None = None,
        voice_profile_id: str | None = None,
        **kwargs,
    ) -> dict:
        del text, reference_audio_path, language_code, voice_profile_id, kwargs
        raise AppError("VOICE_CLONE_PROVIDER_NOT_IMPLEMENTED", "F5TTS provider is not implemented yet", 501)
