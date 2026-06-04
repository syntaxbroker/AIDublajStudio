import base64
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.errors import AppError
from app.providers.lipsync.base import LipSyncProvider


class MuseTalkProvider(LipSyncProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def render(self, *, video_path: Path, audio_path: Path, output_path: Path) -> dict:
        if not video_path.exists():
            raise AppError("MUSETALK_VIDEO_FILE_NOT_FOUND", "MuseTalk input video file not found", 404)
        if not audio_path.exists():
            raise AppError("MUSETALK_AUDIO_FILE_NOT_FOUND", "MuseTalk input audio file not found", 404)
        if not self.settings.musetalk_service_url:
            raise AppError("MUSETALK_SERVICE_URL_MISSING", "MuseTalk service URL is not configured", 503)

        endpoint = f"{self.settings.musetalk_service_url.rstrip('/')}/render"
        model_name = self.settings.musetalk_model_name

        try:
            async with httpx.AsyncClient(timeout=self.settings.musetalk_service_timeout_seconds) as client:
                with video_path.open("rb") as video_handle, audio_path.open("rb") as audio_handle:
                    response = await client.post(
                        endpoint,
                        data={"model_name": model_name},
                        files={
                            "video": (video_path.name, video_handle, "video/mp4"),
                            "audio": (audio_path.name, audio_handle, "audio/wav"),
                        },
                    )
        except httpx.HTTPError as exc:
            raise AppError("MUSETALK_SERVICE_UNAVAILABLE", f"MuseTalk service request failed: {exc}", 502) from exc

        if response.status_code >= 400:
            raise AppError("MUSETALK_RENDER_FAILED", self._extract_error_message(response), 502)

        payload = response.json()
        video_base64 = payload.get("video_base64")
        if not video_base64:
            raise AppError("MUSETALK_RESPONSE_INVALID", "MuseTalk service did not return video data", 502)

        try:
            video_bytes = base64.b64decode(video_base64)
        except Exception as exc:
            raise AppError("MUSETALK_RESPONSE_INVALID", f"MuseTalk returned invalid base64 video: {exc}", 502) from exc

        if not video_bytes:
            raise AppError("MUSETALK_OUTPUT_MISSING", "MuseTalk service returned an empty video", 502)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(video_bytes)

        return {
            "provider": "musetalk",
            "mock": False,
            "model_name": payload.get("model_name") or model_name,
            "source": "musetalk_service",
            "service_metadata": payload.get("metadata_json") or {},
        }

    def _extract_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str):
                return detail
            message = payload.get("message")
            if message:
                return str(message)
        text = response.text.strip()
        return text or f"MuseTalk service returned HTTP {response.status_code}"
