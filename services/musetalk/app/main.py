import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.bootstrap import default_command_template, ensure_runtime_ready


app = FastAPI(title="MuseTalk Service")
app.state.runtime_status = {}


def get_command_template() -> str | None:
    value = (os.getenv("MUSETALK_RENDER_COMMAND") or "").strip()
    if value:
        return value
    return default_command_template()


@app.on_event("startup")
def startup() -> None:
    try:
        app.state.runtime_status = ensure_runtime_ready()
    except Exception as exc:
        app.state.runtime_status = {
            "configured": False,
            "error": str(exc),
            "model_name": os.getenv("MUSETALK_MODEL_NAME", "MuseTalk"),
        }


@app.get("/health")
def health() -> dict:
    runtime_status = dict(app.state.runtime_status or {})
    return {
        "status": "ok",
        "service": "musetalk-service",
        "model_name": os.getenv("MUSETALK_MODEL_NAME", "MuseTalk"),
        "configured": bool(get_command_template()),
        **runtime_status,
    }


@app.post("/render")
async def render(
    model_name: str = Form("MuseTalk"),
    face_mode: str = Form("auto"),
    fps: str = Form(""),
    resolution: str = Form("source"),
    batch_size: str = Form("2"),
    pad_mode: str = Form("clone"),
    use_source_fps: str = Form("true"),
    quality_preset: str = Form("source-native"),
    chunk_mode: str = Form("enabled"),
    chunk_seconds: str = Form("2.5"),
    chunk_overlap_ms: str = Form("160"),
    video: UploadFile = File(...),
    audio: UploadFile = File(...),
) -> dict:
    command_template = get_command_template()
    if not command_template:
        raise HTTPException(status_code=503, detail="MUSETALK_RENDER_COMMAND is not configured")

    with tempfile.TemporaryDirectory(prefix="musetalk-service-") as temp_dir:
        temp_path = Path(temp_dir)
        video_path = temp_path / "input.mp4"
        audio_path = temp_path / "final_dub_audio.wav"
        output_path = temp_path / "lipsync.mp4"

        video_path.write_bytes(await video.read())
        audio_path.write_bytes(await audio.read())

        command = command_template.format(
            video=video_path,
            audio=audio_path,
            output_video=output_path,
            model_name=model_name or os.getenv("MUSETALK_MODEL_NAME", "MuseTalk"),
            face_mode=face_mode,
            fps=fps,
            resolution=resolution,
            batch_size=batch_size,
            pad_mode=pad_mode,
            use_source_fps=use_source_fps,
            quality_preset=quality_preset,
            chunk_mode=chunk_mode,
            chunk_seconds=chunk_seconds,
            chunk_overlap_ms=chunk_overlap_ms,
        )

        input_video_probe = probe_media(video_path)
        input_audio_probe = probe_media(audio_path)
        started_at = time.perf_counter()
        try:
            subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            detail = "\n".join(part for part in [exc.stdout.strip(), exc.stderr.strip()] if part) or str(exc)
            raise HTTPException(status_code=502, detail=f"MuseTalk render command failed: {detail}") from exc
        processing_time_ms = int((time.perf_counter() - started_at) * 1000)

        if not output_path.exists():
            raise HTTPException(status_code=502, detail="MuseTalk render command did not produce output video")

        output_bytes = output_path.read_bytes()
        if not output_bytes:
            raise HTTPException(status_code=502, detail="MuseTalk output video is empty")

        output_probe = probe_media(output_path)
        temporal_validation = read_metadata_sidecar(output_path).get("temporal_validation", {})
        return {
            "video_base64": base64.b64encode(output_bytes).decode("ascii"),
            "model_name": model_name or os.getenv("MUSETALK_MODEL_NAME", "MuseTalk"),
            "metadata_json": {
                "provider": "musetalk",
                "mock": False,
                "source": "musetalk_service",
                "processing_time_ms": processing_time_ms,
                "face_crop_detection_status": "completed",
                "quality_preset": quality_preset,
                "config": {
                    "face_mode": face_mode,
                    "fps": fps or None,
                    "resolution": resolution,
                    "batch_size": parse_int(batch_size, 2),
                    "pad_mode": pad_mode,
                    "use_source_fps": parse_bool(use_source_fps, True),
                    "chunk_mode": chunk_mode,
                    "chunk_seconds": parse_float(chunk_seconds),
                    "chunk_overlap_ms": parse_int(chunk_overlap_ms, 160),
                },
                "input": media_report(input_video_probe, input_audio_probe),
                "output": media_report(output_probe, None),
                "temporal_validation": temporal_validation,
            },
        }


def parse_bool(value: str, default: bool) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def probe_media(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": result.stderr.strip() or f"ffprobe failed with code {result.returncode}"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"ffprobe returned invalid json: {exc}"}


def read_metadata_sidecar(output_path: Path) -> dict:
    sidecar = Path(f"{output_path}.metadata.json")
    if not sidecar.exists():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"metadata sidecar could not be read: {exc}"}


def media_report(video_probe: dict, audio_probe: dict | None) -> dict:
    video_stream = next((stream for stream in video_probe.get("streams", []) if stream.get("codec_type") == "video"), {})
    audio_stream = {}
    if audio_probe is not None:
        audio_stream = next((stream for stream in audio_probe.get("streams", []) if stream.get("codec_type") == "audio"), {})
    return {
        "video_duration_seconds": parse_float(video_probe.get("format", {}).get("duration")),
        "audio_duration_seconds": parse_float((audio_probe or {}).get("format", {}).get("duration")),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "fps": parse_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")),
        "frame_count": parse_int(str(video_stream.get("nb_frames") or ""), 0) or None,
        "audio_channels": audio_stream.get("channels"),
        "audio_sample_rate": parse_int(str(audio_stream.get("sample_rate") or ""), 0) or None,
    }


def parse_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_rate(value: object) -> float | None:
    if not value:
        return None
    try:
        numerator, denominator = str(value).split("/")
        denominator_value = float(denominator)
        return round(float(numerator) / denominator_value, 3) if denominator_value else None
    except (TypeError, ValueError):
        return None
