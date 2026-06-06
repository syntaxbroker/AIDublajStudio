from types import SimpleNamespace

from app.services.transcription_service import TranscriptionService


def _service_with_language(asr_source_language: str) -> TranscriptionService:
    service = TranscriptionService.__new__(TranscriptionService)
    service.settings = SimpleNamespace(asr_source_language=asr_source_language)
    return service


def test_asr_source_language_auto_allows_project_auto_detection() -> None:
    service = _service_with_language("auto")

    assert service._resolve_language_code("auto") == "auto"
    assert service._resolve_language_code(None) == "auto"


def test_project_source_language_can_override_when_global_is_auto() -> None:
    service = _service_with_language("auto")

    assert service._resolve_language_code("en") == "en"


def test_asr_source_language_env_overrides_project_language() -> None:
    service = _service_with_language("sr")

    assert service._resolve_language_code("en") == "sr"
    assert service._resolve_language_code("auto") == "sr"
