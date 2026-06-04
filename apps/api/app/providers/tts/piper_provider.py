from app.core.config import get_settings
from app.core.errors import AppError
from app.providers.tts.base import TTSProvider


class PiperTTSProvider(TTSProvider):
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
        del text, language_code, voice_name, kwargs
        if not self.settings.piper_model_path:
            raise AppError("PIPER_MODEL_PATH_MISSING", "Piper model path is not configured", 500)
        raise AppError("TTS_PROVIDER_NOT_IMPLEMENTED", "Piper provider is not implemented yet", 501)
