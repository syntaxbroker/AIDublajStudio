import base64
import wave
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.errors import AppError
from app.providers.voice_clone.base import VoiceCloneProvider


class CosyVoiceProvider(VoiceCloneProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def synthesize(
        self,
        *,
        text: str,
        reference_audio_path: Path,
        language_code: str | None = None,
        voice_profile_id: str | None = None,
        **kwargs,
    ) -> dict:
        resolved_text = (text or "").strip()
        if not resolved_text:
            raise AppError("VOICE_CLONE_TEXT_REQUIRED", "Voice clone text is required", 409)
        if not reference_audio_path.exists():
            raise AppError("VOICE_REFERENCE_FILE_NOT_FOUND", "Cloned voice reference file not found", 404)
        if not self.settings.cosyvoice_service_url:
            raise AppError("COSYVOICE_SERVICE_URL_MISSING", "CosyVoice service URL is not configured", 503)

        duration_ms, sample_rate = self._probe_reference_audio(reference_audio_path)
        if duration_ms < self.settings.voice_clone_min_sample_duration_ms:
            raise AppError(
                "VOICE_REFERENCE_TOO_SHORT",
                f"Reference sample must be at least {self.settings.voice_clone_min_sample_duration_ms} ms",
                409,
            )

        endpoint = f"{self.settings.cosyvoice_service_url.rstrip('/')}/synthesize"
        model_name = kwargs.get("model_name") or self.settings.cosyvoice_model_name
        reference_text = (kwargs.get("reference_text") or "").strip()
        cosyvoice_mode = kwargs.get("cosyvoice_mode") or ("zero_shot" if reference_text else "cross_lingual")

        try:
            async with httpx.AsyncClient(timeout=self.settings.cosyvoice_service_timeout_seconds) as client:
                with reference_audio_path.open("rb") as reference_handle:
                    response = await client.post(
                        endpoint,
                        data={
                            "text": resolved_text,
                            "language_code": language_code or "tr",
                            "voice_profile_id": voice_profile_id or "",
                            "model_name": model_name,
                            "reference_text": reference_text,
                        },
                        files={
                            "reference_audio": (
                                reference_audio_path.name,
                                reference_handle,
                                "audio/wav",
                            )
                        },
                    )
        except httpx.HTTPError as exc:
            raise AppError("COSYVOICE_SERVICE_UNAVAILABLE", f"CosyVoice service request failed: {exc}", 502) from exc

        if response.status_code >= 400:
            raise AppError("COSYVOICE_SYNTHESIS_FAILED", self._extract_error_message(response), 502)

        content_type = (response.headers.get("content-type") or "").lower()
        response_model_name = response.headers.get("x-model-name") or model_name

        if "application/json" in content_type:
            payload = response.json()
            audio_base64 = payload.get("audio_base64")
            if not audio_base64:
                raise AppError("COSYVOICE_RESPONSE_INVALID", "CosyVoice service did not return audio data", 502)
            try:
                audio_bytes = base64.b64decode(audio_base64)
            except Exception as exc:
                raise AppError("COSYVOICE_RESPONSE_INVALID", f"CosyVoice returned invalid base64 audio: {exc}", 502) from exc
            duration_ms = int(payload.get("duration_ms") or duration_ms)
            sample_rate = int(payload.get("sample_rate") or sample_rate)
            response_model_name = payload.get("model_name") or response_model_name
            response_metadata = payload.get("metadata_json") if isinstance(payload.get("metadata_json"), dict) else {}
        else:
            audio_bytes = response.content
            if not audio_bytes:
                raise AppError("COSYVOICE_OUTPUT_MISSING", "CosyVoice service did not return an audio file", 502)
            response_metadata = {}

        return {
            "provider": "cosyvoice",
            "audio_bytes": audio_bytes,
            "mime_type": "audio/wav",
            "file_extension": ".wav",
            "duration_ms": duration_ms,
            "metadata_json": {
                **response_metadata,
                "cloned": True,
                "language_code": language_code or "tr",
                "model_name": response_model_name,
                "reference_audio_path": str(reference_audio_path),
                "sample_rate": sample_rate,
                "source": "cosyvoice_service",
                "voice_profile_id": voice_profile_id,
                "reference_language": kwargs.get("reference_language"),
                "target_language": kwargs.get("target_language") or language_code or "tr",
                "reference_text_used": bool(reference_text),
                "cosyvoice_mode": cosyvoice_mode,
            },
        }

    def _probe_reference_audio(self, reference_audio_path: Path) -> tuple[int, int]:
        try:
            with wave.open(str(reference_audio_path), "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
        except wave.Error as exc:
            raise AppError("VOICE_REFERENCE_INVALID", f"Reference audio is not a valid WAV file: {exc}", 409) from exc

        if frame_rate <= 0 or frame_count <= 0:
            raise AppError("VOICE_REFERENCE_INVALID", "Reference audio does not contain valid samples", 409)

        duration_ms = int((frame_count / frame_rate) * 1000)
        return duration_ms, frame_rate

    def _extract_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            if isinstance(payload.get("detail"), str):
                return payload["detail"]
            if isinstance(payload.get("error"), dict):
                message = payload["error"].get("message")
                if message:
                    return str(message)
            message = payload.get("message")
            if message:
                return str(message)
        text = response.text.strip()
        return text or f"CosyVoice service returned HTTP {response.status_code}"
