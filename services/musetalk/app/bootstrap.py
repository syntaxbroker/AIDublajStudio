from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import gdown
from huggingface_hub import snapshot_download


REPO_MARKER = ".codex_requirements_installed"


def env_flag(name: str, default: bool = False) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def get_repo_dir() -> Path:
    return Path(os.getenv("MUSETALK_REPO_DIR", "/opt/musetalk/MuseTalk"))


def get_model_dir() -> Path:
    return Path(os.getenv("MUSETALK_MODEL_DIR", str(get_repo_dir() / "models")))


def get_runtime_runner_path() -> Path:
    return Path(os.getenv("MUSETALK_RUNNER_PATH", "/workspace/services/musetalk/app/run_musetalk.py"))


def ensure_runtime_ready() -> dict:
    repo_dir = get_repo_dir()
    model_dir = get_model_dir()
    bootstrap_enabled = env_flag("MUSETALK_BOOTSTRAP", False)

    if bootstrap_enabled:
        bootstrap_repo(repo_dir)
        install_repo_requirements(repo_dir)
        bootstrap_model(repo_dir, model_dir)
        patch_preprocessing(repo_dir)

    runner_path = get_runtime_runner_path()
    configured = runner_path.exists() and repo_dir.exists() and model_dir.exists() and _required_model_files_exist(model_dir)
    return {
        "configured": configured,
        "repo_dir": str(repo_dir),
        "model_dir": str(model_dir),
        "runner_path": str(runner_path),
        "bootstrap_enabled": bootstrap_enabled,
        "device": os.getenv("MUSETALK_DEVICE", "auto"),
    }


def default_command_template() -> str | None:
    repo_dir = get_repo_dir()
    model_dir = get_model_dir()
    runner_path = get_runtime_runner_path()
    if not runner_path.exists() or not repo_dir.exists() or not model_dir.exists():
        return None

    device = os.getenv("MUSETALK_DEVICE", "auto")
    return (
        f"{sys.executable} {runner_path} "
        f"--repo-dir {repo_dir} "
        f"--model-dir {model_dir} "
        f"--device {device} "
        f"--video {{video}} "
        f"--audio {{audio}} "
        f"--output-video {{output_video}} "
        f"--model-name {{model_name}}"
    )


def bootstrap_repo(repo_dir: Path) -> None:
    repo_url = (os.getenv("MUSETALK_REPO_URL") or "https://github.com/TMElyralab/MuseTalk.git").strip()
    if repo_dir.exists():
        return
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", repo_url, str(repo_dir)], check=True)


def install_repo_requirements(repo_dir: Path) -> None:
    marker = repo_dir / REPO_MARKER
    if marker.exists():
        return
    install_mode = (os.getenv("MUSETALK_INSTALL_MODE") or "minimal").strip().lower()
    requirements_path = repo_dir / "requirements.txt"
    if install_mode == "minimal":
        requirements_path = Path("/workspace/services/musetalk/minimal_inference_requirements.txt")
    if not requirements_path.exists():
        raise RuntimeError(f"MuseTalk requirements file not found at {requirements_path}")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(requirements_path)], check=True)
    marker.write_text("installed\n", encoding="utf-8")


def bootstrap_model(repo_dir: Path, model_dir: Path) -> None:
    del repo_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    if _required_model_files_exist(model_dir):
        return
    snapshot_download(
        "TMElyralab/MuseTalk",
        local_dir=str(model_dir),
        allow_patterns=[
            "musetalk/musetalk.json",
            "musetalk/pytorch_model.bin",
            "musetalkV15/musetalk.json",
            "musetalkV15/unet.pth",
        ],
    )
    snapshot_download(
        "stabilityai/sd-vae-ft-mse",
        local_dir=str(model_dir / "sd-vae"),
        allow_patterns=["config.json", "diffusion_pytorch_model.bin"],
    )
    snapshot_download(
        "openai/whisper-tiny",
        local_dir=str(model_dir / "whisper"),
        allow_patterns=["config.json", "pytorch_model.bin", "preprocessor_config.json"],
    )
    snapshot_download(
        "yzd-v/DWPose",
        local_dir=str(model_dir / "dwpose"),
        allow_patterns=["dw-ll_ucoco_384.pth"],
    )
    snapshot_download(
        "ByteDance/LatentSync",
        local_dir=str(model_dir / "syncnet"),
        allow_patterns=["latentsync_syncnet.pt"],
    )
    face_parse_dir = model_dir / "face-parse-bisent"
    face_parse_dir.mkdir(parents=True, exist_ok=True)
    bisent_path = face_parse_dir / "79999_iter.pth"
    if not bisent_path.exists():
        gdown.download(id="154JgKpzCPW82qINcVieuPH3fZ2e0P812", output=str(bisent_path), quiet=False)
    resnet_path = face_parse_dir / "resnet18-5c106cde.pth"
    if not resnet_path.exists():
        import urllib.request

        urllib.request.urlretrieve("https://download.pytorch.org/models/resnet18-5c106cde.pth", resnet_path)


def _required_model_files_exist(model_dir: Path) -> bool:
    return all(
        (model_dir / path).exists()
        for path in [
            "musetalkV15/unet.pth",
            "musetalkV15/musetalk.json",
            "sd-vae/config.json",
            "whisper/config.json",
            "face-parse-bisent/79999_iter.pth",
            "face-parse-bisent/resnet18-5c106cde.pth",
        ]
    )


def patch_preprocessing(repo_dir: Path) -> None:
    if not env_flag("MUSETALK_PATCH_PREPROCESSING", True):
        return
    preprocessing_path = repo_dir / "musetalk" / "utils" / "preprocessing.py"
    if not preprocessing_path.exists():
        return
    source = preprocessing_path.read_text(encoding="utf-8")
    if "MUSETALK_CODEX_BBOX_PREPROCESSING_PATCH" in source:
        return
    preprocessing_path.write_text(SIMPLIFIED_PREPROCESSING, encoding="utf-8")


SIMPLIFIED_PREPROCESSING = '''import cv2
import numpy as np
import torch
from face_detection import FaceAlignment, LandmarksType
from tqdm import tqdm

# MUSETALK_CODEX_BBOX_PREPROCESSING_PATCH: use MuseTalk's vendored face detector
# bbox directly, avoiding the optional compiled MMPose/MMCV landmark runtime.
device = "cuda" if torch.cuda.is_available() else "cpu"
fa = FaceAlignment(LandmarksType._2D, flip_input=False, device=device)
coord_placeholder = (0.0, 0.0, 0.0, 0.0)


def read_imgs(img_list):
    frames = []
    print("reading images...")
    for img_path in tqdm(img_list):
        frames.append(cv2.imread(img_path))
    return frames


def get_bbox_range(img_list, upperbondrange=0):
    del upperbondrange
    return f"Total frame: {len(img_list)} Using detector bounding boxes"


def get_landmark_and_bbox(img_list, upperbondrange=0):
    del upperbondrange
    frames = read_imgs(img_list)
    batch_size_fa = 1
    batches = [frames[i:i + batch_size_fa] for i in range(0, len(frames), batch_size_fa)]
    coords_list = []
    print("get face bounding boxes with the default value")
    for fb in tqdm(batches):
        bbox = fa.get_detections_for_batch(np.asarray(fb))
        for f in bbox:
            if f is None:
                coords_list.append(coord_placeholder)
                continue
            x1, y1, x2, y2 = [int(value) for value in f]
            x1 = max(0, x1)
            y1 = max(0, y1)
            coords_list.append((x1, y1, x2, y2))
    print("********************************************bbox_shift parameter adjustment**********************************************************")
    print(f"Total frame: {len(frames)} Using detector bounding boxes")
    print("*************************************************************************************************************************************")
    return coords_list, frames
'''


def _copy_missing_tree(source: Path, target: Path) -> None:
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
