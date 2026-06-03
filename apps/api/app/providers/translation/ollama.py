import httpx

from app.core.config import get_settings
from app.providers.translation.base import TranslationProvider


class OllamaTranslationProvider(TranslationProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def translate(self, text: str, source_language: str, target_language: str) -> dict:
        prompt = (
            f"Translate the following text from {source_language} to {target_language}. "
            "Return only the translated text.\n\n"
            f"Text: {text}"
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
            "source_language": source_language,
            "target_language": target_language,
            "translated_text": payload["response"].strip(),
            "metadata_json": {"model": self.settings.ollama_translation_model},
        }
