from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-dir", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--video", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output-video", required=True)
    parser.add_argument("--model-name", default="MuseTalk")
    args = parser.parse_args()

    repo_dir = Path(args.repo_dir)
    model_dir = Path(args.model_dir)
    output_video = Path(args.output_video)
    output_video.parent.mkdir(parents=True, exist_ok=True)

    if not repo_dir.exists():
        raise SystemExit(f"MuseTalk repo directory does not exist: {repo_dir}")
    if not model_dir.exists():
        raise SystemExit(f"MuseTalk model directory does not exist: {model_dir}")

    with tempfile.TemporaryDirectory(prefix="musetalk-run-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        result_dir = temp_dir / "results"
        config_path = temp_dir / "inference.yaml"
        result_name = output_video.name
        config = {
            "aidublaj": {
                "video_path": str(Path(args.video).resolve()),
                "audio_path": str(Path(args.audio).resolve()),
                "result_name": result_name,
            }
        }
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        command = [
            sys.executable,
            str(Path(__file__).with_name("run_musetalk_inference.py")),
            "--inference_config",
            str(config_path),
            "--result_dir",
            str(result_dir),
            "--unet_model_path",
            str(model_dir / "musetalkV15" / "unet.pth"),
            "--unet_config",
            str(model_dir / "musetalkV15" / "musetalk.json"),
            "--whisper_dir",
            str(model_dir / "whisper"),
            "--version",
            "v15",
            "--batch_size",
            os.getenv("MUSETALK_BATCH_SIZE", "2"),
        ]
        if _use_float16(args.device):
            command.append("--use_float16")

        subprocess.run(command, cwd=repo_dir, check=True)
        produced = result_dir / "v15" / result_name
        if not produced.exists():
            candidates = sorted(result_dir.rglob("*.mp4"))
            if len(candidates) == 1:
                produced = candidates[0]
            else:
                candidate_list = ", ".join(str(item) for item in candidates) or "none"
                raise SystemExit(f"MuseTalk did not produce expected output: {produced}; candidates: {candidate_list}")
        shutil.copy2(produced, output_video)


def _use_float16(device: str) -> bool:
    value = (os.getenv("MUSETALK_USE_FLOAT16") or "").strip().lower()
    if value:
        return value in {"1", "true", "yes", "on"}
    return device.lower() not in {"cpu", "none"}


if __name__ == "__main__":
    main()
