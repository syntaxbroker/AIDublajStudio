from __future__ import annotations

import runpy
import atexit
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import torch


def main() -> None:
    if (os.getenv("MUSETALK_DEVICE") or "").strip().lower() in {"cpu", "none"}:
        torch.cuda.is_available = lambda: False
    # MMEngine versions used by MuseTalk register transformers.Adafactor into
    # torch.optim; PyTorch 2.7 already ships that name, so remove it for this
    # child process before importing mmpose.
    if hasattr(torch.optim, "Adafactor"):
        delattr(torch.optim, "Adafactor")
    original_torch_load = torch.load

    def torch_load_with_legacy_default(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original_torch_load(*args, **kwargs)

    torch.load = torch_load_with_legacy_default
    patch_preprocessing_runtime(Path(os.getcwd()))
    install_frame_writer_debug()
    sys.path.insert(0, os.getcwd())
    sys.argv = ["scripts.inference", *sys.argv[1:]]
    runpy.run_module("scripts.inference", run_name="__main__")


def patch_preprocessing_runtime(repo_dir: Path) -> None:
    preprocessing_path = repo_dir / "musetalk" / "utils" / "preprocessing.py"
    if not preprocessing_path.exists():
        return
    source = preprocessing_path.read_text(encoding="utf-8")
    if "MUSETALK_CODEX_BBOX_FILL_PATCH" in source:
        return
    if "coords_list.append(coord_placeholder)" not in source:
        return
    patched = source.replace(
        "coords_list.append(coord_placeholder)",
        "coords_list.append(coord_placeholder)  # MUSETALK_CODEX_BBOX_FILL_PATCH",
        1,
    )
    marker = "    print(\"********************************************bbox_shift parameter adjustment**********************************************************\")"
    if marker in patched:
        patched = patched.replace(
            marker,
            "    coords_list = _aidublaj_fill_missing_bboxes(coords_list, coord_placeholder)\n"
            "    missing_count = sum(1 for coord in coords_list if coord == coord_placeholder)\n"
            "    print(f\"Aidublaj bbox fill remaining placeholders: {missing_count}\")\n"
            + marker,
            1,
        )
    helper = '''


def _aidublaj_fill_missing_bboxes(coords_list, coord_placeholder):
    valid_indices = [index for index, coord in enumerate(coords_list) if coord != coord_placeholder]
    if not valid_indices:
        return coords_list
    filled = list(coords_list)
    for index, coord in enumerate(filled):
        if coord != coord_placeholder:
            continue
        previous_indices = [candidate for candidate in valid_indices if candidate < index]
        next_indices = [candidate for candidate in valid_indices if candidate > index]
        previous_index = previous_indices[-1] if previous_indices else None
        next_index = next_indices[0] if next_indices else None
        if previous_index is None:
            replacement = filled[next_index]
        elif next_index is None:
            replacement = filled[previous_index]
        elif index - previous_index <= next_index - index:
            replacement = filled[previous_index]
        else:
            replacement = filled[next_index]
        filled[index] = replacement
    return filled
'''
    patched = patched.rstrip() + helper + "\n"
    preprocessing_path.write_text(patched, encoding="utf-8")


def install_frame_writer_debug() -> None:
    if (os.getenv("MUSETALK_DEBUG_FRAME_WRITER") or "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    try:
        import cv2
    except Exception:
        return

    original_imwrite = cv2.imwrite
    original_subprocess_run = subprocess.run
    original_subprocess_call = subprocess.call
    original_os_system = os.system
    source_video_path = find_inference_video_path()
    result_dir_path = find_arg_path("--result_dir")
    source_capture = cv2.VideoCapture(str(source_video_path)) if source_video_path else None
    expected_frame_count = get_source_frame_count(source_capture)
    source_frame_cache: dict[int, object] = {}
    stats = {
        "attempts": 0,
        "success": 0,
        "failed": 0,
        "png_indices": [],
        "failed_paths": [],
        "fallback_frame_count": 0,
        "fallback_indices": [],
        "fallback_strategy": "source_frame",
        "source_video_path": str(source_video_path) if source_video_path else None,
        "expected_frame_count": expected_frame_count,
        "sequence_fix_count": 0,
        "sequence_fix_first_missing_index": None,
    }
    state = {"last_index": None, "last_image": None}

    def debug_imwrite(filename, img, params=None):
        path = str(filename)
        if path.endswith(".png") and "/results/" in path.replace("\\", "/"):
            stem = os.path.splitext(os.path.basename(path))[0]
            if stem.isdigit():
                current_index = int(stem)
                fill_missing_frames(
                    original_imwrite=original_imwrite,
                    params=params,
                    target_path=Path(path),
                    current_index=current_index,
                    state=state,
                    stats=stats,
                    source_capture=source_capture,
                    source_frame_cache=source_frame_cache,
                )
        result = original_imwrite(filename, img) if params is None else original_imwrite(filename, img, params)
        if path.endswith(".png") and "/results/" in path.replace("\\", "/"):
            stats["attempts"] += 1
            if result:
                stats["success"] += 1
                state["last_image"] = img.copy() if hasattr(img, "copy") else img
            else:
                stats["failed"] += 1
                stats["failed_paths"].append(path)
            stem = os.path.splitext(os.path.basename(path))[0]
            if stem.isdigit():
                current_index = int(stem)
                stats["png_indices"].append(current_index)
                state["last_index"] = current_index
                print(
                    f"MUSETALK_FRAME_WRITE index={current_index} success={bool(result)} path={path}",
                    flush=True,
                )
        return result

    def subprocess_run_with_sequence_fix(command, *args, **kwargs):
        ensure_frame_sequence_before_ffmpeg(
            command=command,
            original_imwrite=original_imwrite,
            stats=stats,
            state=state,
            source_capture=source_capture,
            source_frame_cache=source_frame_cache,
            expected_frame_count=expected_frame_count,
        )
        return original_subprocess_run(command, *args, **kwargs)

    def subprocess_call_with_sequence_fix(command, *args, **kwargs):
        ensure_frame_sequence_before_ffmpeg(
            command=command,
            original_imwrite=original_imwrite,
            stats=stats,
            state=state,
            source_capture=source_capture,
            source_frame_cache=source_frame_cache,
            expected_frame_count=expected_frame_count,
        )
        return original_subprocess_call(command, *args, **kwargs)

    def os_system_with_sequence_fix(command):
        ensure_frame_sequence_before_ffmpeg(
            command=command,
            original_imwrite=original_imwrite,
            stats=stats,
            state=state,
            source_capture=source_capture,
            source_frame_cache=source_frame_cache,
            expected_frame_count=expected_frame_count,
        )
        return original_os_system(command)

    def print_summary():
        indices = stats["png_indices"]
        first_missing = None
        if indices:
            present = set(indices)
            for candidate in range(min(indices), max(indices) + 2):
                if candidate not in present:
                    first_missing = candidate
                    break
        summary = {
            "attempts": stats["attempts"],
            "success": stats["success"],
            "failed": stats["failed"],
            "min_index": min(indices) if indices else None,
            "max_index": max(indices) if indices else None,
            "first_missing_index": first_missing,
            "failed_paths": stats["failed_paths"][-5:],
            "fallback_frame_count": stats["fallback_frame_count"],
            "fallback_strategy": stats["fallback_strategy"],
            "fallback_indices": stats["fallback_indices"][:2000],
            "source_video_path": stats["source_video_path"],
            "expected_frame_count": stats["expected_frame_count"],
            "sequence_fix_count": stats["sequence_fix_count"],
            "sequence_fix_first_missing_index": stats["sequence_fix_first_missing_index"],
        }
        print("MUSETALK_FRAME_WRITER_SUMMARY " + str(summary), flush=True)
        if result_dir_path:
            try:
                result_dir_path.mkdir(parents=True, exist_ok=True)
                (result_dir_path / "frame_writer_debug.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as exc:
                print(f"MUSETALK_FRAME_WRITER_SUMMARY_WRITE_FAILED error={exc}", flush=True)
        if source_capture is not None:
            source_capture.release()

    cv2.imwrite = debug_imwrite
    subprocess.run = subprocess_run_with_sequence_fix
    subprocess.call = subprocess_call_with_sequence_fix
    os.system = os_system_with_sequence_fix
    atexit.register(print_summary)


def find_inference_video_path() -> Path | None:
    try:
        import yaml
    except Exception:
        yaml = None
    args = sys.argv[1:]
    config_path = None
    for index, value in enumerate(args):
        if value == "--inference_config" and index + 1 < len(args):
            config_path = Path(args[index + 1])
            break
    if not config_path or not config_path.exists() or yaml is None:
        return None
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    for item in config.values():
        if isinstance(item, dict) and item.get("video_path"):
            return Path(item["video_path"])
    return None


def find_arg_path(name: str) -> Path | None:
    args = sys.argv[1:]
    for index, value in enumerate(args):
        if value == name and index + 1 < len(args):
            return Path(args[index + 1])
    return None


def fill_missing_frames(
    *,
    original_imwrite,
    params,
    target_path: Path,
    current_index: int,
    state: dict,
    stats: dict,
    source_capture,
    source_frame_cache: dict[int, object],
) -> None:
    last_index = state.get("last_index")
    if last_index is None or current_index <= last_index + 1:
        return
    for missing_index in range(last_index + 1, current_index):
        fallback = read_source_frame(source_capture, source_frame_cache, missing_index)
        strategy = "source_frame"
        if fallback is None:
            fallback = state.get("last_image")
            strategy = "previous_successful_frame"
        if fallback is None:
            continue
        missing_path = target_path.with_name(f"{missing_index:08d}.png")
        result = original_imwrite(str(missing_path), fallback) if params is None else original_imwrite(str(missing_path), fallback, params)
        print(
            f"MUSETALK_FRAME_FALLBACK index={missing_index} success={bool(result)} strategy={strategy} path={missing_path}",
            flush=True,
        )
        if result:
            stats["fallback_frame_count"] += 1
            stats["fallback_indices"].append(missing_index)
            stats["png_indices"].append(missing_index)
            if strategy != "source_frame" and stats.get("fallback_strategy") == "source_frame":
                stats["fallback_strategy"] = "source_frame_with_previous_frame_fallback"


def read_source_frame(source_capture, source_frame_cache: dict[int, object], frame_index: int):
    if source_capture is None:
        return None
    if frame_index in source_frame_cache:
        return source_frame_cache[frame_index]
    import cv2

    source_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = source_capture.read()
    if not ok:
        return None
    source_frame_cache[frame_index] = frame
    if len(source_frame_cache) > 32:
        for key in sorted(source_frame_cache)[:8]:
            source_frame_cache.pop(key, None)
    return frame


def get_source_frame_count(source_capture) -> int | None:
    if source_capture is None:
        return None
    try:
        import cv2

        value = int(round(source_capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    except Exception:
        return None
    return value if value > 0 else None


def ensure_frame_sequence_before_ffmpeg(
    *,
    command,
    original_imwrite,
    stats: dict,
    state: dict,
    source_capture,
    source_frame_cache: dict[int, object],
    expected_frame_count: int | None,
) -> None:
    image_pattern = extract_image2_pattern(command)
    if not image_pattern or "%08d.png" not in image_pattern:
        return
    if not expected_frame_count:
        return

    pattern_path = Path(image_pattern)
    frame_dir = pattern_path.parent
    if not frame_dir.exists():
        return

    present = {
        int(item.stem)
        for item in frame_dir.glob("*.png")
        if item.stem.isdigit()
    }
    missing_indices = [index for index in range(expected_frame_count) if index not in present]
    if not missing_indices:
        return

    if stats.get("sequence_fix_first_missing_index") is None:
        stats["sequence_fix_first_missing_index"] = missing_indices[0]
    written = 0
    for missing_index in missing_indices:
        fallback = read_source_frame(source_capture, source_frame_cache, missing_index)
        strategy = "source_frame"
        if fallback is None:
            fallback = find_previous_png_frame(frame_dir, missing_index)
            strategy = "previous_written_png"
        if fallback is None:
            fallback = state.get("last_image")
            strategy = "previous_successful_frame"
        if fallback is None:
            continue
        missing_path = frame_dir / f"{missing_index:08d}.png"
        result = original_imwrite(str(missing_path), fallback)
        print(
            f"MUSETALK_FRAME_FALLBACK index={missing_index} success={bool(result)} strategy={strategy} path={missing_path}",
            flush=True,
        )
        if result:
            written += 1
            stats["fallback_frame_count"] += 1
            stats["fallback_indices"].append(missing_index)
            stats["png_indices"].append(missing_index)
            if strategy != "source_frame" and stats.get("fallback_strategy") == "source_frame":
                stats["fallback_strategy"] = "source_frame_with_previous_frame_fallback"

    stats["sequence_fix_count"] += written
    print(
        "MUSETALK_FRAME_SEQUENCE_FIX "
        + str(
            {
                "directory": str(frame_dir),
                "expected_frame_count": expected_frame_count,
                "present_before": len(present),
                "missing_before": len(missing_indices),
                "fallback_written": written,
                "first_missing_index": missing_indices[0] if missing_indices else None,
            }
        ),
        flush=True,
    )


def extract_image2_pattern(command) -> str | None:
    if isinstance(command, (list, tuple)):
        values = [str(item) for item in command]
        if "-f" in values and "image2" in values and "-i" in values:
            for index, value in enumerate(values):
                if value == "-i" and index + 1 < len(values) and "%08d.png" in values[index + 1]:
                    return values[index + 1]
        return None
    text = str(command)
    if "image2" not in text or "%08d.png" not in text:
        return None
    quoted = re.search(r"-i\s+['\"]([^'\"]*%08d\.png)['\"]", text)
    if quoted:
        return quoted.group(1)
    unquoted = re.search(r"-i\s+(\S*%08d\.png)", text)
    return unquoted.group(1) if unquoted else None


def find_previous_png_frame(frame_dir: Path, missing_index: int):
    try:
        import cv2
    except Exception:
        return None
    for candidate in range(missing_index - 1, -1, -1):
        path = frame_dir / f"{candidate:08d}.png"
        if path.exists():
            return cv2.imread(str(path))
    return None


if __name__ == "__main__":
    main()
