from app.core.config import get_settings
from app.providers.asr.faster_whisper import FasterWhisperASRProvider
from app.providers.asr.mock import MockASRProvider
from app.providers.diarization.mock import MockDiarizationProvider
from app.providers.diarization.pyannote_provider import PyannoteDiarizationProvider
from app.providers.lipsync.mock import MockLipSyncProvider
from app.providers.tts.cosyvoice_provider import CosyVoiceTTSProvider
from app.providers.tts.edge_tts_provider import EdgeTTSProvider
from app.providers.tts.mock import MockTTSProvider
from app.providers.tts.piper_provider import PiperTTSProvider
from app.providers.voice_clone.cosyvoice_provider import CosyVoiceProvider
from app.providers.voice_clone.f5tts_provider import F5TTSProvider
from app.providers.voice_clone.mock import MockVoiceCloneProvider
from app.providers.translation.mock import MockTranslationProvider
from app.providers.translation.ollama import OllamaTranslationProvider
from app.providers.translation.openai_provider import OpenAITranslationProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._providers = {
            "ASR": {"mock": MockASRProvider, "faster_whisper": FasterWhisperASRProvider},
            "DIARIZATION": {"mock": MockDiarizationProvider, "pyannote": PyannoteDiarizationProvider},
            "TRANSLATION": {
                "mock": MockTranslationProvider,
                "ollama": OllamaTranslationProvider,
                "openai": OpenAITranslationProvider,
            },
            "TTS": {
                "mock": MockTTSProvider,
                "edge_tts": EdgeTTSProvider,
                "piper": PiperTTSProvider,
                "cosyvoice": CosyVoiceTTSProvider,
            },
            "VOICE_CLONE": {
                "mock": MockVoiceCloneProvider,
                "cosyvoice": CosyVoiceProvider,
                "f5tts": F5TTSProvider,
            },
            "LIP_SYNC": {"mock": MockLipSyncProvider},
        }

    def get(self, capability: str, provider_key: str | None = None):
        resolved_provider_key = provider_key or self._default_provider_key(capability)
        try:
            provider_cls = self._providers[capability][resolved_provider_key]
        except KeyError as exc:
            raise ValueError(f"Provider not registered for {capability}:{resolved_provider_key}") from exc
        return provider_cls()

    def _default_provider_key(self, capability: str) -> str:
        if capability == "ASR":
            return self.settings.asr_provider
        if capability == "DIARIZATION":
            return self.settings.diarization_provider
        if capability == "TRANSLATION":
            return self.settings.translation_provider
        if capability == "TTS":
            return self.settings.tts_provider
        if capability == "VOICE_CLONE":
            return self.settings.voice_clone_provider
        return "mock"
