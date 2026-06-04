import base64
import os
import subprocess
import tempfile
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
        )

        try:
            subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            detail = "\n".join(part for part in [exc.stdout.strip(), exc.stderr.strip()] if part) or str(exc)
            raise HTTPException(status_code=502, detail=f"MuseTalk render command failed: {detail}") from exc

        if not output_path.exists():
            raise HTTPException(status_code=502, detail="MuseTalk render command did not produce output video")

        output_bytes = output_path.read_bytes()
        if not output_bytes:
            raise HTTPException(status_code=502, detail="MuseTalk output video is empty")

        return {
            "video_base64": base64.b64encode(output_bytes).decode("ascii"),
            "model_name": model_name or os.getenv("MUSETALK_MODEL_NAME", "MuseTalk"),
            "metadata_json": {
                "provider": "musetalk",
                "mock": False,
                "source": "musetalk_service",
            },
        }
