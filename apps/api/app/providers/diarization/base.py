from abc import ABC, abstractmethod


class DiarizationProvider(ABC):
    capability = "DIARIZATION"

    @abstractmethod
    async def diarize(self, source_path: str) -> dict:
        raise NotImplementedError
