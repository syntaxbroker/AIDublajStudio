from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_MARKER = ".codex_requirements_installed"


def env_flag(name: str, default: bool = False) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def get_repo_dir() -> Path:
    return Path(os.getenv("COSYVOICE_REPO_DIR", "/opt/cosyvoice/CosyVoice"))


def get_model_dir() -> Path:
    return Path(os.getenv("COSYVOICE_MODEL_DIR", "/models/CosyVoice-300M"))


def get_runtime_runner_path() -> Path:
    return Path(os.getenv("COSYVOICE_RUNNER_PATH", "/workspace/services/cosyvoice/app/run_cosyvoice.py"))


def ensure_runtime_ready() -> dict:
    repo_dir = get_repo_dir()
    model_dir = get_model_dir()
    bootstrap_enabled = env_flag("COSYVOICE_BOOTSTRAP", False)

    if bootstrap_enabled:
        bootstrap_repo(repo_dir)
        install_repo_requirements(repo_dir)
        bootstrap_model(model_dir)

    runner_path = get_runtime_runner_path()
    configured = runner_path.exists() and repo_dir.exists() and model_dir.exists()
    return {
        "configured": configured,
        "repo_dir": str(repo_dir),
        "model_dir": str(model_dir),
        "runner_path": str(runner_path),
        "bootstrap_enabled": bootstrap_enabled,
        "device": os.getenv("COSYVOICE_DEVICE", "auto"),
    }


def default_command_template() -> str | None:
    repo_dir = get_repo_dir()
    model_dir = get_model_dir()
    runner_path = get_runtime_runner_path()
    if not runner_path.exists() or not repo_dir.exists() or not model_dir.exists():
        return None

    device = os.getenv("COSYVOICE_DEVICE", "auto")
    command = (
        f"{sys.executable} {runner_path} "
        f"--repo-dir {repo_dir} "
        f"--model-dir {model_dir} "
        f"--device {device} "
        f"--text-file {{text_file}} "
        f"--reference-audio {{reference_audio}} "
        f"--output-audio {{output_audio}} "
        f"--language-code {{language_code}} "
        f"--voice-profile-id {{voice_profile_id}} "
        f"--model-name {{model_name}} "
        f"--reference-text-file {{reference_text_file}}"
    )
    return command


def bootstrap_repo(repo_dir: Path) -> None:
    repo_url = (os.getenv("COSYVOICE_REPO_URL") or "https://github.com/FunAudioLLM/CosyVoice.git").strip()
    if repo_dir.exists():
        return
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--recursive", repo_url, str(repo_dir)],
        check=True,
    )


def install_repo_requirements(repo_dir: Path) -> None:
    marker = repo_dir / REPO_MARKER
    if marker.exists():
        return
    install_mode = (os.getenv("COSYVOICE_INSTALL_MODE") or "minimal").strip().lower()
    requirements_path = repo_dir / "requirements.txt"
    if install_mode == "minimal":
        minimal_path = Path("/workspace/services/cosyvoice/minimal_inference_requirements.txt")
        if not minimal_path.exists():
            raise RuntimeError(f"CosyVoice minimal inference requirements not found at {minimal_path}")
        requirements_path = minimal_path
    elif not requirements_path.exists():
        raise RuntimeError(f"CosyVoice requirements.txt not found at {requirements_path}")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "setuptools==70.0.0", "wheel", "numpy==1.26.4", "cython"],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-build-isolation", "-r", str(requirements_path)],
        check=True,
    )
    marker.write_text("installed\n", encoding="utf-8")


def bootstrap_model(model_dir: Path) -> None:
    model_id = (os.getenv("COSYVOICE_MODEL_ID") or "").strip()
    if model_dir.exists():
        return
    if not model_id:
        raise RuntimeError("COSYVOICE_MODEL_ID must be set when COSYVOICE_BOOTSTRAP=1")
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    download_script = (
        "from huggingface_hub import snapshot_download;"
        f"snapshot_download('{model_id}', local_dir=r'{model_dir.as_posix()}')"
    )
    subprocess.run([sys.executable, "-c", download_script], check=True)
