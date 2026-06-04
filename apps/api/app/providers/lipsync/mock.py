import shutil
from pathlib import Path

from app.providers.lipsync.base import LipSyncProvider


class MockLipSyncProvider(LipSyncProvider):
    async def render(self, *, video_path: Path, audio_path: Path, output_path: Path) -> dict:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(video_path, output_path)
        return {
            "provider": "mock",
            "source": "video_copy",
            "video_path": str(video_path),
            "audio_path": str(audio_path),
        }
