import re

import httpx

from app.core.config import get_settings
from app.providers.translation.base import TranslationProvider


class OllamaTranslationProvider(TranslationProvider):
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
        prompt = self._build_prompt(
            text=text,
            source_language=source_language,
            target_language=target_language,
        )
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.settings.ollama_base_url}/api/generate",
                json={
                    "model": self.settings.ollama_translation_model,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
        translated_text = _clean_model_text(payload["response"])
        return {
            "provider": "ollama",
            "source_language": source_language,
            "target_language": target_language,
            "translated_text": translated_text,
            "faithful_text": translated_text,
            "metadata_json": {
                "model": self.settings.ollama_translation_model,
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
        prompt = self._build_duration_adaptation_prompt(
            text=text,
            target_language=target_language,
            target_duration_ms=target_duration_ms,
            previous_duration_ms=previous_duration_ms,
            attempt_no=attempt_no,
        )
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.settings.ollama_base_url}/api/generate",
                json={
                    "model": self.settings.ollama_translation_model,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
        return {
            "provider": "ollama",
            "adapted_text": _clean_model_text(payload["response"]),
            "metadata_json": {
                "model": self.settings.ollama_translation_model,
                "translation_stage": "tts_duration_feedback_adaptation",
                "duration_adaptation_in_provider": True,
                "attempt_no": attempt_no,
                "target_duration_ms": target_duration_ms,
                "previous_duration_ms": previous_duration_ms,
            },
        }

    def _build_prompt(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        return (
            "Translate faithfully for dubbing.\n"
            f"Source language: {source_language}\n"
            f"Target language: {target_language}\n"
            "Rules:\n"
            "- Preserve every claim, negation, entity, amount, and intent.\n"
            "- Do not shorten by deleting meaning.\n"
            "- Produce natural spoken target-language text.\n"
            "- Return only the translation, with no notes and no quotation marks.\n\n"
            f"Text: {text}"
        )

    def _build_duration_adaptation_prompt(
        self,
        *,
        text: str,
        target_language: str,
        target_duration_ms: int,
        previous_duration_ms: int | None,
        attempt_no: int,
    ) -> str:
        target_seconds = max(target_duration_ms, 1) / 1000
        previous = f" Previous TTS duration was {previous_duration_ms / 1000:.2f} seconds." if previous_duration_ms else ""
        pressure = "Be concise." if attempt_no == 1 else "Be very concise and remove filler words only."
        return (
            "Rewrite this already-translated dubbing line for timing.\n"
            f"Target language: {target_language}\n"
            f"Target spoken duration: about {target_seconds:.1f} seconds.{previous}\n"
            "Rules:\n"
            "- Preserve the core meaning, entities, negation, and intent.\n"
            "- Do not add new information.\n"
            "- Make it natural spoken Turkish for dubbing.\n"
            f"- {pressure}\n"
            "- Return only the rewritten line, with no notes and no quotation marks.\n\n"
            f"Line: {text}"
        )


def _clean_model_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.strip().strip('"').strip("'").strip()
    return cleaned.splitlines()[0].strip() if "\n" in cleaned else cleaned
