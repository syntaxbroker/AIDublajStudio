import httpx

from app.core.config import get_settings
from app.core.errors import AppError
from app.providers.translation.base import TranslationProvider


class OpenAITranslationProvider(TranslationProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def translate(self, text: str, source_language: str, target_language: str) -> dict:
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
                            "content": "You are a translation engine. Return only the translated text.",
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
            "metadata_json": {"model": self.settings.openai_translation_model},
        }
