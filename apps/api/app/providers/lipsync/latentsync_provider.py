from pathlib import Path

from app.providers.lipsync.base import LipSyncProvider


class LatentSyncProvider(LipSyncProvider):
    async def render(self, *, video_path: Path, audio_path: Path, output_path: Path) -> dict:
        raise NotImplementedError("LatentSync lip sync provider is not implemented yet")
