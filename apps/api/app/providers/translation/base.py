from abc import ABC, abstractmethod


class TranslationProvider(ABC):
    capability = "TRANSLATION"

    @abstractmethod
    async def translate(self, text: str, source_language: str, target_language: str) -> dict:
        raise NotImplementedError
