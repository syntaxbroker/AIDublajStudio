from abc import ABC, abstractmethod


class ASRProvider(ABC):
    capability = "ASR"

    @abstractmethod
    async def transcribe(self, *args, **kwargs) -> dict:
        raise NotImplementedError
