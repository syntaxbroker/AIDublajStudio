from app.providers.diarization.base import DiarizationProvider


class MockDiarizationProvider(DiarizationProvider):
    async def diarize(self, source_path: str) -> dict:
        return {
            "provider": "mock",
            "segments": [
                {
                    "start_ms": 0,
                    "end_ms": 1500,
                    "speaker_label": "speaker_01",
                    "confidence": 0.9821,
                    "metadata_json": {"source_path": source_path},
                },
                {
                    "start_ms": 1500,
                    "end_ms": 4000,
                    "speaker_label": "speaker_02",
                    "confidence": 0.9714,
                    "metadata_json": {"source_path": source_path},
                },
            ],
        }
