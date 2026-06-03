from app.providers.translation.base import TranslationProvider


class MockTranslationProvider(TranslationProvider):
    async def translate(self, text: str, source_language: str, target_language: str) -> dict:
        translated_text = self._translate(text, source_language, target_language)
        return {
            "provider": "mock",
            "source_language": source_language,
            "target_language": target_language,
            "translated_text": translated_text,
            "metadata_json": {},
        }

    def _translate(self, text: str, source_language: str, target_language: str) -> str:
        if target_language != "tr":
            return text

        dictionary = {
            "hello": "Merhaba",
            "hello john.": "Merhaba John.",
            "hello john": "Merhaba John.",
            "how are you?": "Nasılsın?",
            "how are you": "Nasılsın?",
            "i am fine": "İyiyim.",
            "i am fine.": "İyiyim.",
        }
        normalized = text.strip().lower()
        if normalized in dictionary:
            return dictionary[normalized]
        if source_language == "sr":
            serbian = {
                "zdravo": "Merhaba",
                "kako si": "Nasılsın?",
                "dobro sam": "İyiyim.",
            }
            return serbian.get(normalized, f"[TR] {text.strip()}")
        return f"[TR] {text.strip()}"
