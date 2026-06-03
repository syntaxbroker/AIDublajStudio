from app.core.errors import AppError
from app.providers.tts.base import TTSProvider


class EdgeTTSProvider(TTSProvider):
    async def synthesize(
        self,
        *,
        text: str,
        language_code: str | None = None,
        voice_name: str | None = None,
        **kwargs,
    ) -> dict:
        del text, language_code, voice_name, kwargs
        raise AppError("TTS_PROVIDER_NOT_IMPLEMENTED", "Edge TTS provider is not implemented yet", 501)
