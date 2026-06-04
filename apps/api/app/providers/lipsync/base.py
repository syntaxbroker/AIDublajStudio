from abc import ABC, abstractmethod
from pathlib import Path


class LipSyncProvider(ABC):
    capability = "LIP_SYNC"

    @abstractmethod
    async def render(self, *, video_path: Path, audio_path: Path, output_path: Path) -> dict:
        raise NotImplementedError
