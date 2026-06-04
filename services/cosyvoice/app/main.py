import base64
import os
import subprocess
import tempfile
import wave
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.bootstrap import default_command_template, ensure_runtime_ready


app = FastAPI(title="CosyVoice Service")
app.state.runtime_status = {}


def get_command_template() -> str | None:
    value = (os.getenv("COSYVOICE_SYNTH_COMMAND") or "").strip()
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
            "model_name": os.getenv("COSYVOICE_MODEL_NAME", "CosyVoice"),
        }


@app.get("/health")
def health() -> dict:
    runtime_status = dict(app.state.runtime_status or {})
    return {
        "status": "ok",
        "service": "cosyvoice-service",
        "model_name": os.getenv("COSYVOICE_MODEL_NAME", "CosyVoice"),
        "configured": bool(get_command_template()),
        **runtime_status,
    }


@app.post("/synthesize")
async def synthesize(
    text: str = Form(...),
    language_code: str = Form("tr"),
    voice_profile_id: str = Form(""),
    model_name: str = Form("CosyVoice"),
    reference_text: str = Form(""),
    reference_audio: UploadFile = File(...),
) -> dict:
    command_template = get_command_template()
    if not command_template:
        raise HTTPException(status_code=503, detail="COSYVOICE_SYNTH_COMMAND is not configured")

    resolved_text = (text or "").strip()
    if not resolved_text:
        raise HTTPException(status_code=409, detail="text is required")

    with tempfile.TemporaryDirectory(prefix="cosyvoice-service-") as temp_dir:
        temp_path = Path(temp_dir)
        reference_path = temp_path / "reference.wav"
        output_path = temp_path / "output.wav"
        text_path = temp_path / "text.txt"
        reference_text_path = temp_path / "reference_text.txt"

        reference_path.write_bytes(await reference_audio.read())
        text_path.write_text(resolved_text, encoding="utf-8")
        reference_text_path.write_text((reference_text or "").strip(), encoding="utf-8")

        command = command_template.format(
            text=resolved_text,
            text_file=text_path,
            reference_audio=reference_path,
            output_audio=output_path,
            reference_text_file=reference_text_path,
            language_code=language_code,
            voice_profile_id=voice_profile_id,
            model_name=model_name,
        )

        try:
            subprocess.run(
                command,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise HTTPException(status_code=502, detail=f"CosyVoice synthesis command failed: {detail}") from exc

        if not output_path.exists():
            raise HTTPException(status_code=502, detail="CosyVoice synthesis command did not produce output audio")

        try:
            with wave.open(str(output_path), "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
        except wave.Error as exc:
            raise HTTPException(status_code=502, detail=f"CosyVoice output is not a valid WAV file: {exc}") from exc

        if frame_rate <= 0 or frame_count <= 0:
            raise HTTPException(status_code=502, detail="CosyVoice output audio is empty")

        audio_bytes = output_path.read_bytes()
        duration_ms = int((frame_count / frame_rate) * 1000)
        return {
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "duration_ms": duration_ms,
            "sample_rate": frame_rate,
            "model_name": model_name or os.getenv("COSYVOICE_MODEL_NAME", "CosyVoice"),
        }
