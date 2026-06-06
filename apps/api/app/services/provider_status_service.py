from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.runtime import ProviderStatusItem, ProviderStatusResponse


PROVIDER_CAPABILITIES = {
    "ASR_PROVIDER": "asr_provider",
    "TRANSLATION_PROVIDER": "translation_provider",
    "TTS_PROVIDER": "tts_provider",
    "VOICE_CLONE_PROVIDER": "voice_clone_provider",
    "VOICE_CONVERSION_PROVIDER": "voice_conversion_provider",
    "LIP_SYNC_PROVIDER": "lip_sync_provider",
}


class ProviderStatusService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def status(self) -> ProviderStatusResponse:
        providers = [
            ProviderStatusItem(
                capability=capability,
                provider=str(getattr(self.settings, setting_name)),
                is_mock=str(getattr(self.settings, setting_name)).lower() == "mock",
            )
            for capability, setting_name in PROVIDER_CAPABILITIES.items()
        ]
        has_mock_provider = any(item.is_mock for item in providers)
        warning = None
        if has_mock_provider:
            warning = (
                "One or more mock providers are active. Mock providers are for tests only "
                "and can generate fake timelines, fake durations, and beep-tone audio."
            )
        return ProviderStatusResponse(
            allow_mock_providers=self.settings.allow_mock_providers,
            has_mock_provider=has_mock_provider,
            providers=providers,
            warning=warning,
        )

    def enforce_real_processing_allowed(self) -> None:
        status = self.status()
        if not status.has_mock_provider or status.allow_mock_providers:
            return
        mock_capabilities = ", ".join(item.capability for item in status.providers if item.is_mock)
        raise AppError(
            "MOCK_PROVIDERS_BLOCKED",
            (
                "Real UI processing is blocked because mock providers are active "
                f"({mock_capabilities}). Set real providers, or explicitly set "
                "ALLOW_MOCK_PROVIDERS=true for test-only runs."
            ),
            409,
        )
