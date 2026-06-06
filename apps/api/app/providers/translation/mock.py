from app.providers.translation.base import TranslationProvider


class MockTranslationProvider(TranslationProvider):
    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        *,
        source_duration_ms: int | None = None,
        target_duration_ms: int | None = None,
    ) -> dict:
        translated_text = self._translate(text, source_language, target_language)
        return {
            "provider": "mock",
            "source_language": source_language,
            "target_language": target_language,
            "translated_text": translated_text,
            "faithful_text": translated_text,
            "metadata_json": {
                "translation_stage": "faithful",
                "duration_adaptation_in_provider": False,
            },
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

    async def adapt_for_tts_duration(
        self,
        *,
        text: str,
        target_language: str,
        target_duration_ms: int,
        previous_duration_ms: int | None = None,
        attempt_no: int = 1,
    ) -> dict:
        del previous_duration_ms
        words = text.strip().split()
        if target_language == "tr" and len(words) > 3:
            keep = max(3, int(len(words) * (0.75 if attempt_no == 1 else 0.6)))
            adapted_text = " ".join(words[:keep]).strip(" ,;:")
            if text.strip().endswith((".", "!", "?")):
                adapted_text += text.strip()[-1]
        else:
            adapted_text = text.strip()
        return {
            "provider": "mock",
            "adapted_text": adapted_text,
            "metadata_json": {
                "translation_stage": "tts_duration_feedback_adaptation",
                "duration_adaptation_in_provider": True,
                "attempt_no": attempt_no,
                "target_duration_ms": target_duration_ms,
            },
        }
