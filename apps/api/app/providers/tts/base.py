from abc import ABC, abstractmethod


class TTSProvider(ABC):
    capability = "TTS"

    @abstractmethod
    async def synthesize(
        self,
        *,
        text: str,
        language_code: str | None = None,
        voice_name: str | None = None,
        **kwargs,
    ) -> dict:
        raise NotImplementedError
