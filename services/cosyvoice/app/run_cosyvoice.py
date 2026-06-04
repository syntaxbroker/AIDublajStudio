from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CosyVoice zero-shot or cross-lingual synthesis")
    parser.add_argument("--repo-dir", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--text-file", required=True)
    parser.add_argument("--reference-audio", required=True)
    parser.add_argument("--output-audio", required=True)
    parser.add_argument("--reference-text-file", required=False, default="")
    parser.add_argument("--language-code", required=False, default="tr")
    parser.add_argument("--voice-profile-id", required=False, default="")
    parser.add_argument("--model-name", required=False, default="CosyVoice")
    parser.add_argument("--device", required=False, default="auto")
    return parser.parse_args()


def choose_device(requested: str) -> str:
    import torch

    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("COSYVOICE_DEVICE=cuda but CUDA is not available in the container")
        return "cuda"
    if requested == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    return "cpu"


def main() -> int:
    args = parse_args()
    repo_dir = Path(args.repo_dir).resolve()
    model_dir = Path(args.model_dir).resolve()
    text_file = Path(args.text_file).resolve()
    reference_audio = Path(args.reference_audio).resolve()
    output_audio = Path(args.output_audio).resolve()
    reference_text_file = Path(args.reference_text_file).resolve() if args.reference_text_file else None

    if not repo_dir.exists():
        raise RuntimeError(f"CosyVoice repo not found: {repo_dir}")
    if not model_dir.exists():
        raise RuntimeError(f"CosyVoice model dir not found: {model_dir}")
    if not text_file.exists():
        raise RuntimeError(f"text file not found: {text_file}")
    if not reference_audio.exists():
        raise RuntimeError(f"reference audio not found: {reference_audio}")

    runner_dir = Path(__file__).resolve().parent
    sys.path = [item for item in sys.path if Path(item or ".").resolve() != runner_dir]
    sys.path.insert(0, str(repo_dir))
    matcha_dir = repo_dir / "third_party" / "Matcha-TTS"
    if matcha_dir.exists():
        sys.path.insert(0, str(matcha_dir))

    device = choose_device(args.device)

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    text = text_file.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError("target text is empty")

    reference_text = ""
    if reference_text_file and reference_text_file.exists():
        reference_text = reference_text_file.read_text(encoding="utf-8").strip()

    cosyvoice = AutoModel(model_dir=str(model_dir))

    generators = None
    if reference_text:
        generators = cosyvoice.inference_zero_shot(
            text,
            reference_text,
            str(reference_audio),
            stream=False,
        )
    else:
        generators = cosyvoice.inference_cross_lingual(
            text,
            str(reference_audio),
            stream=False,
        )

    first_result = next(iter(generators), None)
    if not first_result:
        raise RuntimeError("CosyVoice did not return any audio segments")

    output_audio.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(
        str(output_audio),
        first_result["tts_speech"],
        cosyvoice.sample_rate,
        encoding="PCM_S",
        bits_per_sample=16,
    )

    metadata_path = output_audio.with_suffix(".json")
    metadata_path.write_text(
        (
            "{"
            f"\"device\": \"{device}\", "
            f"\"model_name\": \"{args.model_name}\", "
            f"\"voice_profile_id\": \"{args.voice_profile_id}\", "
            f"\"reference_text_used\": {str(bool(reference_text)).lower()}, "
            f"\"sample_rate\": {int(cosyvoice.sample_rate)}"
            "}"
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
