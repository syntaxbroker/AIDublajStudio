from abc import ABC, abstractmethod
from pathlib import Path


class VoiceConversionProvider(ABC):
    capability = "VOICE_CONVERSION"

    @abstractmethod
    def convert(
        self,
        *,
        source_audio_path: Path,
        reference_audio_path: Path,
        output_audio_path: Path,
        options: dict | None = None,
    ) -> dict:
        raise NotImplementedError
