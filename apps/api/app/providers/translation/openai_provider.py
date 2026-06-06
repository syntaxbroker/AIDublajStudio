import httpx

from app.core.config import get_settings
from app.core.errors import AppError
from app.providers.translation.base import TranslationProvider


class OpenAITranslationProvider(TranslationProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        *,
        source_duration_ms: int | None = None,
        target_duration_ms: int | None = None,
    ) -> dict:
        if not self.settings.openai_api_key:
            raise AppError("OPENAI_API_KEY_MISSING", "OpenAI API key is not configured", 500)

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.settings.openai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.openai_translation_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": self._system_prompt(target_language),
                        },
                        {
                            "role": "user",
                            "content": f"Translate from {source_language} to {target_language}: {text}",
                        },
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
        translated_text = payload["choices"][0]["message"]["content"].strip()
        return {
            "provider": "openai",
            "source_language": source_language,
            "target_language": target_language,
            "translated_text": translated_text,
            "faithful_text": translated_text,
            "metadata_json": {
                "model": self.settings.openai_translation_model,
                "translation_stage": "faithful",
                "duration_adaptation_in_provider": False,
            },
        }

    async def adapt_for_tts_duration(
        self,
        *,
        text: str,
        target_language: str,
        target_duration_ms: int,
        previous_duration_ms: int | None = None,
        attempt_no: int = 1,
    ) -> dict:
        if not self.settings.openai_api_key:
            raise AppError("OPENAI_API_KEY_MISSING", "OpenAI API key is not configured", 500)

        target_seconds = max(target_duration_ms, 1) / 1000
        previous = f" Previous TTS duration was {previous_duration_ms / 1000:.2f} seconds." if previous_duration_ms else ""
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.settings.openai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": self.settings.openai_translation_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                f"Rewrite {target_language} dubbing text to fit timing. Preserve core meaning, "
                                "entities, negation, and intent. Return only the rewritten line."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Rewrite this line so it can be spoken in about {target_seconds:.1f} seconds."
                                f"{previous}\nLine: {text}"
                            ),
                        },
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
        return {
            "provider": "openai",
            "adapted_text": payload["choices"][0]["message"]["content"].strip().strip('"'),
            "metadata_json": {
                "model": self.settings.openai_translation_model,
                "translation_stage": "tts_duration_feedback_adaptation",
                "duration_adaptation_in_provider": True,
                "attempt_no": attempt_no,
                "target_duration_ms": target_duration_ms,
                "previous_duration_ms": previous_duration_ms,
            },
        }

    def _system_prompt(self, target_language: str) -> str:
        return (
            f"You are a faithful translation engine for {target_language}. "
            "Preserve every claim, negation, entity, amount, and intent. "
            "Do not shorten by deleting meaning. Return only the translated text, with no notes."
        )
