import asyncio
from collections.abc import Iterable
from pathlib import Path

from app.core.config import get_settings
from app.providers.asr.base import ASRProvider


class FasterWhisperASRProvider(ASRProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def transcribe(self, *, source_path: str, language_code: str | None = None, **kwargs) -> dict:
        del kwargs
        return await asyncio.to_thread(self._transcribe_sync, source_path, language_code)

    def _transcribe_sync(self, source_path: str, language_code: str | None) -> dict:
        requested_language = (language_code or "auto").strip().lower()
        resolved_language = None if requested_language == "auto" else requested_language
        model, device, compute_type = self._create_model()
        segments, info = model.transcribe(
            audio=str(Path(source_path)),
            language=resolved_language,
            word_timestamps=self.settings.asr_word_timestamps,
        )
        normalized_segments = [self._normalize_segment(index, segment) for index, segment in enumerate(segments)]
        return {
            "provider": "faster_whisper",
            "requested_language": requested_language,
            "language_code": info.language,
            "language_probability": getattr(info, "language_probability", None),
            "device": device,
            "compute_type": compute_type,
            "segments": normalized_segments,
        }

    def _create_model(self):
        from faster_whisper import WhisperModel

        preferred_device = self._preferred_device()
        preferred_compute_type = self._preferred_compute_type(preferred_device)
        return (
            WhisperModel(self.settings.asr_model_size, device=preferred_device, compute_type=preferred_compute_type),
            preferred_device,
            preferred_compute_type,
        )

    def _preferred_device(self) -> str:
        if self.settings.asr_device != "auto":
            return self.settings.asr_device
        return "cuda"

    def _preferred_compute_type(self, device: str) -> str:
        if self.settings.asr_compute_type != "auto":
            return self.settings.asr_compute_type
        return "float16" if device == "cuda" else "int8"

    def _normalize_segment(self, segment_index: int, segment) -> dict:
        words = self._normalize_words(getattr(segment, "words", []) or [])
        probabilities = [word["probability"] for word in words if word.get("probability") is not None]
        confidence = round(sum(probabilities) / len(probabilities), 4) if probabilities else None

        metadata_json = {
            "avg_logprob": getattr(segment, "avg_logprob", None),
            "compression_ratio": getattr(segment, "compression_ratio", None),
            "no_speech_prob": getattr(segment, "no_speech_prob", None),
        }
        if words:
            metadata_json["words"] = words

        return {
            "segment_index": segment_index,
            "start_ms": int(float(segment.start) * 1000),
            "end_ms": int(float(segment.end) * 1000),
            "speaker_label": None,
            "text": segment.text.strip(),
            "confidence": confidence,
            "metadata_json": metadata_json,
        }

    def _normalize_words(self, words: Iterable) -> list[dict]:
        normalized = []
        for word in words:
            normalized.append(
                {
                    "word": word.word,
                    "start_ms": int(float(word.start) * 1000) if getattr(word, "start", None) is not None else None,
                    "end_ms": int(float(word.end) * 1000) if getattr(word, "end", None) is not None else None,
                    "probability": round(float(word.probability), 4) if getattr(word, "probability", None) is not None else None,
                }
            )
        return normalized
