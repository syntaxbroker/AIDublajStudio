from app.providers.asr.base import ASRProvider


class MockASRProvider(ASRProvider):
    async def transcribe(self, *, source_path: str, language_code: str | None = None, **kwargs) -> dict:
        del kwargs
        requested_language = language_code or "auto"
        return {
            "provider": "mock",
            "requested_language": requested_language,
            "language_code": "en" if requested_language == "auto" else requested_language,
            "language_probability": 1.0,
            "segments": [
                {
                    "segment_index": 0,
                    "start_ms": 0,
                    "end_ms": 900,
                    "speaker_label": "speaker_01",
                    "text": "Hello",
                    "confidence": 0.9821,
                    "metadata_json": {"source_path": source_path},
                },
                {
                    "segment_index": 1,
                    "start_ms": 1100,
                    "end_ms": 2200,
                    "speaker_label": "speaker_01",
                    "text": "How are you",
                    "confidence": 0.9715,
                    "metadata_json": {"source_path": source_path},
                },
                {
                    "segment_index": 2,
                    "start_ms": 2450,
                    "end_ms": 3200,
                    "speaker_label": "speaker_02",
                    "text": "I am fine",
                    "confidence": 0.9654,
                    "metadata_json": {"source_path": source_path},
                },
            ],
        }
