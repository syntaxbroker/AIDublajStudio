from abc import ABC, abstractmethod
from pathlib import Path


class VoiceCloneProvider(ABC):
    capability = "VOICE_CLONE"

    @abstractmethod
    async def synthesize(
        self,
        *,
        text: str,
        reference_audio_path: Path,
        language_code: str | None = None,
        voice_profile_id: str | None = None,
        **kwargs,
    ) -> dict:
        raise NotImplementedError
