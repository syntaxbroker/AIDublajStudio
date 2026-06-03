import asyncio

from app.core.config import get_settings
from app.core.errors import AppError
from app.providers.diarization.base import DiarizationProvider


class PyannoteDiarizationProvider(DiarizationProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def diarize(self, source_path: str) -> dict:
        return await asyncio.to_thread(self._diarize_sync, source_path)

    def _diarize_sync(self, source_path: str) -> dict:
        if not self.settings.pyannote_auth_token:
            raise AppError("PYANNOTE_AUTH_TOKEN_MISSING", "Pyannote auth token is not configured", 500)

        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(
            self.settings.pyannote_pipeline_name,
            use_auth_token=self.settings.pyannote_auth_token,
        )
        diarization = pipeline(source_path)

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(
                {
                    "start_ms": int(float(turn.start) * 1000),
                    "end_ms": int(float(turn.end) * 1000),
                    "speaker_label": str(speaker),
                    "confidence": None,
                    "metadata_json": {},
                }
            )

        return {"provider": "pyannote", "segments": segments}
