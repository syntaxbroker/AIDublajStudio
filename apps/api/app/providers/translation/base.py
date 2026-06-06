from abc import ABC, abstractmethod


class TranslationProvider(ABC):
    capability = "TRANSLATION"

    @abstractmethod
    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        *,
        source_duration_ms: int | None = None,
        target_duration_ms: int | None = None,
    ) -> dict:
        raise NotImplementedError

    async def adapt_for_tts_duration(
        self,
        *,
        text: str,
        target_language: str,
        target_duration_ms: int,
        previous_duration_ms: int | None = None,
        attempt_no: int = 1,
    ) -> dict:
        del target_language, target_duration_ms, previous_duration_ms, attempt_no
        return {
            "provider": "base",
            "adapted_text": text.strip(),
            "metadata_json": {"duration_adaptation_in_provider": False},
        }
