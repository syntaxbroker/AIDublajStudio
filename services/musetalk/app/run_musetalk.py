from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--face-mode", default="auto")
    parser.add_argument("--target-fps", default="")
    parser.add_argument("--resolution", default="source")
    parser.add_argument("--batch-size", default="")
    parser.add_argument("--pad-mode", default="clone")
    parser.add_argument("--use-source-fps", default="true")
    parser.add_argument("--quality-preset", default="source-fps")
    parser.add_argument("--chunk-mode", default=os.getenv("MUSETALK_CHUNK_MODE", "enabled"))
    parser.add_argument("--chunk-seconds", default=os.getenv("MUSETALK_CHUNK_SECONDS", "2.5"))
    parser.add_argument("--chunk-overlap-ms", default=os.getenv("MUSETALK_CHUNK_OVERLAP_MS", "160"))
    args = parser.parse_args()
    if args.device.lower() in {"cpu", "none"}:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

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
        result_name = output_video.name
        video_path = Path(args.video).resolve()
        max_width = _resolution_max_width(args.resolution)
        if max_width is None:
            max_width = (os.getenv("MUSETALK_MAX_WIDTH") or "").strip()
        if not max_width and args.device.lower() in {"cpu", "none"}:
            max_width = "640"
        if max_width:
            scaled_video = temp_dir / "input-640.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_path),
                    "-vf",
                    f"scale={int(max_width)}:-2",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-an",
                    str(scaled_video),
                ],
                check=True,
            )
            video_path = scaled_video
        expected_duration_seconds = _target_duration_seconds(
            audio_path=Path(args.audio).resolve(),
            video_path=Path(args.video).resolve(),
        )
        expected_fps = _target_output_fps(args=args, source_video=Path(args.video).resolve())
        if _chunk_mode_enabled(args.chunk_mode):
            produced, temporal_report = _render_chunked_musetalk(
                args=args,
                repo_dir=repo_dir,
                model_dir=model_dir,
                source_video=video_path,
                source_audio=Path(args.audio).resolve(),
                output_name=result_name,
                temp_dir=temp_dir,
                expected_duration_seconds=expected_duration_seconds,
                expected_fps=expected_fps,
            )
        else:
            produced, temporal_report = _render_single_musetalk(
                args=args,
                repo_dir=repo_dir,
                model_dir=model_dir,
                video_path=video_path,
                audio_path=Path(args.audio).resolve(),
                output_name=result_name,
                temp_dir=temp_dir,
                expected_duration_seconds=expected_duration_seconds,
                expected_fps=expected_fps,
            )
        shutil.copy2(produced, output_video)
        _write_metadata_sidecar(output_video, temporal_report)


def _render_single_musetalk(
    *,
    args,
    repo_dir: Path,
    model_dir: Path,
    video_path: Path,
    audio_path: Path,
    output_name: str,
    temp_dir: Path,
    expected_duration_seconds: float | None,
    expected_fps: float | None,
) -> tuple[Path, dict]:
    produced = _run_musetalk_inference(
        args=args,
        repo_dir=repo_dir,
        model_dir=model_dir,
        video_path=video_path,
        audio_path=audio_path,
        output_name=output_name,
        result_dir=temp_dir / "results",
        config_path=temp_dir / "inference.yaml",
    )
    temporal_report = _validate_musetalk_temporal_output(
        produced,
        expected_duration_seconds=expected_duration_seconds,
        expected_fps=expected_fps,
        stage="raw",
    )
    produced = _pad_video_stream_to_duration(
        produced,
        target_duration_seconds=expected_duration_seconds,
        temp_dir=temp_dir,
        pad_mode=args.pad_mode,
    )
    produced = _normalize_output_fps(produced, target_fps=expected_fps, temp_dir=temp_dir)
    produced = _apply_quality_preset(
        produced,
        quality_preset=args.quality_preset,
        source_video=Path(args.video).resolve(),
        temp_dir=temp_dir,
    )
    final_report = _validate_musetalk_temporal_output(
        produced,
        expected_duration_seconds=expected_duration_seconds,
        expected_fps=expected_fps,
        stage="final",
    )["raw_output"]
    temporal_report.update(
        {
            "chunk_mode": False,
            "chunk_count": 1,
            "failed_chunk_index": None,
            "concat_method": None,
            "final_output": final_report,
        }
    )
    return produced, temporal_report


def _run_musetalk_inference(
    *,
    args,
    repo_dir: Path,
    model_dir: Path,
    video_path: Path,
    audio_path: Path,
    output_name: str,
    result_dir: Path,
    config_path: Path,
) -> Path:
    config = {
        "aidublaj": {
            "video_path": str(video_path),
            "audio_path": str(audio_path),
            "result_name": output_name,
        }
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
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
        args.batch_size or os.getenv("MUSETALK_BATCH_SIZE", "2"),
    ]
    if _use_float16(args.device):
        command.append("--use_float16")

    try:
        subprocess.run(command, cwd=repo_dir, check=True)
    except subprocess.CalledProcessError as exc:
        debug_report = _inspect_musetalk_result_dir(result_dir)
        message = json.dumps(
            {
                "returncode": exc.returncode,
                "result_dir": str(result_dir),
                "frame_writer_debug": debug_report,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        raise SystemExit(f"MuseTalk inference failed with frame writer debug: {message}") from exc
    produced = result_dir / "v15" / output_name
    if produced.exists():
        _write_frame_writer_debug_sidecar(produced, _inspect_musetalk_result_dir(result_dir))
        return produced
    candidates = sorted(result_dir.rglob("*.mp4"))
    if len(candidates) == 1:
        _write_frame_writer_debug_sidecar(candidates[0], _inspect_musetalk_result_dir(result_dir))
        return candidates[0]
    candidate_list = ", ".join(str(item) for item in candidates) or "none"
    raise SystemExit(f"MuseTalk did not produce expected output: {produced}; candidates: {candidate_list}")


def _render_chunked_musetalk(
    *,
    args,
    repo_dir: Path,
    model_dir: Path,
    source_video: Path,
    source_audio: Path,
    output_name: str,
    temp_dir: Path,
    expected_duration_seconds: float | None,
    expected_fps: float | None,
) -> tuple[Path, dict]:
    if not expected_duration_seconds:
        raise SystemExit("MuseTalk chunk mode requires a measurable source duration")

    chunk_seconds = _env_or_arg_float(args.chunk_seconds, "MUSETALK_CHUNK_SECONDS", 2.5)
    overlap_seconds = _env_or_arg_float(args.chunk_overlap_ms, "MUSETALK_CHUNK_OVERLAP_MS", 160.0) / 1000.0
    if chunk_seconds <= 0:
        raise SystemExit("MuseTalk chunk mode requires MUSETALK_CHUNK_SECONDS > 0")
    if overlap_seconds < 0 or overlap_seconds >= chunk_seconds:
        raise SystemExit("MuseTalk chunk overlap must be >= 0 and less than chunk seconds")

    intervals = _chunk_intervals(expected_duration_seconds, chunk_seconds, overlap_seconds)
    chunk_outputs: list[Path] = []
    chunk_reports: list[dict] = []
    try:
        concat_cursor = 0.0
        for index, interval in enumerate(intervals):
            chunk_video = temp_dir / f"chunk-{index:04d}.mp4"
            chunk_audio = temp_dir / f"chunk-{index:04d}.wav"
            _extract_video_chunk(source_video, chunk_video, start_seconds=interval["start"], duration_seconds=interval["duration"])
            _extract_audio_chunk(source_audio, chunk_audio, start_seconds=interval["start"], duration_seconds=interval["duration"])

            source_fallback = False
            fallback_reason = None
            try:
                produced = _run_musetalk_inference(
                    args=args,
                    repo_dir=repo_dir,
                    model_dir=model_dir,
                    video_path=chunk_video,
                    audio_path=chunk_audio,
                    output_name=f"chunk-{index:04d}.mp4",
                    result_dir=temp_dir / f"results-{index:04d}",
                    config_path=temp_dir / f"inference-{index:04d}.yaml",
                )
            except SystemExit as exc:
                if not _is_no_output_error(str(exc)):
                    raise
                produced = _source_chunk_fallback(
                    chunk_video,
                    chunk_audio,
                    temp_dir / f"chunk-{index:04d}-source-fallback.mp4",
                )
                source_fallback = True
                fallback_reason = str(exc)
            raw_report = _validate_musetalk_temporal_output(
                produced,
                expected_duration_seconds=interval["duration"],
                expected_fps=expected_fps,
                stage=f"chunk-{index:04d}-raw",
                allow_static=source_fallback,
            )["raw_output"]
            trim_start = max(0.0, concat_cursor - interval["start"])
            trim_duration = max(0.0, interval["end"] - concat_cursor)
            if trim_duration <= 0:
                continue
            trimmed = _trim_chunk_output(
                produced,
                temp_dir / f"chunk-{index:04d}-trimmed.mp4",
                trim_start_seconds=trim_start,
                duration_seconds=trim_duration,
                fps=expected_fps,
            )
            concat_cursor = interval["end"]
            trimmed_report = _validate_musetalk_temporal_output(
                trimmed,
                expected_duration_seconds=trim_duration,
                expected_fps=expected_fps,
                stage=f"chunk-{index:04d}-trimmed",
                allow_static=source_fallback,
            )["raw_output"]
            chunk_outputs.append(trimmed)
            chunk_reports.append(
                {
                    "chunk_index": index,
                    "start_ms": _milliseconds(interval["start"]),
                    "end_ms": _milliseconds(interval["end"]),
                    "duration_ms": _milliseconds(interval["duration"]),
                    "trim_start_ms": _milliseconds(trim_start),
                    "concat_duration_ms": _milliseconds(trim_duration),
                    "raw_output": raw_report,
                    "trimmed_output": trimmed_report,
                    "source_fallback": source_fallback,
                    "source_fallback_reason": fallback_reason,
                }
            )
    except SystemExit as exc:
        raise SystemExit(
            "MuseTalk chunk render failed: "
            + json.dumps(
                {
                    "failed_chunk_index": len(chunk_reports),
                    "chunk_count": len(intervals),
                    "error": str(exc),
                    "completed_chunks": chunk_reports,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        ) from exc

    concatenated = _concat_chunks(chunk_outputs, temp_dir / "lipsync-chunked.mp4")
    concatenated = _normalize_output_fps(concatenated, target_fps=expected_fps, temp_dir=temp_dir)
    concatenated = _trim_chunk_output(
        concatenated,
        temp_dir / "lipsync-chunked-duration-fixed.mp4",
        trim_start_seconds=0.0,
        duration_seconds=expected_duration_seconds,
        fps=expected_fps,
    )
    concatenated = _apply_quality_preset(
        concatenated,
        quality_preset=args.quality_preset,
        source_video=Path(args.video).resolve(),
        temp_dir=temp_dir,
    )
    final_report = _validate_musetalk_temporal_output(
        concatenated,
        expected_duration_seconds=expected_duration_seconds,
        expected_fps=expected_fps,
        stage="chunked-final",
    )["raw_output"]
    temporal_report = {
        "stage": "chunked",
        "chunk_mode": True,
        "chunk_seconds": chunk_seconds,
        "chunk_overlap_ms": int(round(overlap_seconds * 1000)),
        "chunk_count": len(chunk_reports),
        "failed_chunk_index": None,
        "concat_method": "overlap_trim_concat_demuxer",
        "per_chunk_duration_ms": [item["raw_output"].get("raw_output_duration_ms") for item in chunk_reports],
        "per_chunk_static_ratio": [item["raw_output"].get("adjacent_static_frame_ratio") for item in chunk_reports],
        "chunks": chunk_reports,
        "raw_output": final_report,
        "final_output": final_report,
    }
    return concatenated, temporal_report


def _chunk_intervals(total_seconds: float, chunk_seconds: float, overlap_seconds: float) -> list[dict]:
    if total_seconds <= chunk_seconds:
        return [{"start": 0.0, "end": total_seconds, "duration": total_seconds}]
    starts = []
    step = chunk_seconds - overlap_seconds
    start = 0.0
    while start + chunk_seconds < total_seconds - 0.001:
        starts.append(start)
        start += step
    final_start = max(0.0, total_seconds - chunk_seconds)
    if not starts or final_start > starts[-1] + 0.001:
        starts.append(final_start)

    intervals = []
    for start in starts:
        end = min(start + chunk_seconds, total_seconds)
        intervals.append({"start": start, "end": end, "duration": end - start})
    return intervals


def _extract_video_chunk(source: Path, target: Path, *, start_seconds: float, duration_seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-ss",
            f"{start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            "-vf",
            "setpts=PTS-STARTPTS",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(target),
        ],
        check=True,
    )


def _extract_audio_chunk(source: Path, target: Path, *, start_seconds: float, duration_seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-ss",
            f"{start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            "-af",
            "asetpts=PTS-STARTPTS",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        check=True,
    )


def _is_no_output_error(message: str) -> bool:
    return "MuseTalk did not produce expected output" in message and "candidates: none" in message


def _source_chunk_fallback(video_path: Path, audio_path: Path, target: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(target),
        ],
        check=True,
    )
    return target


def _trim_chunk_output(
    source: Path,
    target: Path,
    *,
    trim_start_seconds: float,
    duration_seconds: float,
    fps: float | None,
) -> Path:
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{trim_start_seconds:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration_seconds:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
    ]
    if fps:
        command.extend(["-r", f"{fps:.3f}"])
    command.extend(["-c:a", "aac", "-b:a", "128k", str(target)])
    subprocess.run(command, check=True)
    return target


def _concat_chunks(chunks: list[Path], target: Path) -> Path:
    list_path = target.with_suffix(".txt")
    lines = []
    for chunk in chunks:
        escaped = str(chunk).replace("'", "'\\''")
        lines.append(f"file '{escaped}'\n")
    list_path.write_text("".join(lines), encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(target),
        ],
        check=True,
    )
    return target


def _inspect_musetalk_result_dir(result_dir: Path) -> dict:
    frame_writer_summary = {}
    summary_path = result_dir / "frame_writer_debug.json"
    if summary_path.exists():
        try:
            frame_writer_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            frame_writer_summary = {"error": str(exc)}
    png_dirs = []
    for directory in sorted({item.parent for item in result_dir.rglob("*.png")}):
        pngs = sorted(directory.glob("*.png"))
        indices = []
        for item in pngs:
            try:
                indices.append(int(item.stem))
            except ValueError:
                continue
        first_missing = None
        if indices:
            present = set(indices)
            for candidate in range(min(indices), max(indices) + 2):
                if candidate not in present:
                    first_missing = candidate
                    break
        png_dirs.append(
            {
                "directory": str(directory),
                "png_count": len(pngs),
                "numeric_png_count": len(indices),
                "min_index": min(indices) if indices else None,
                "max_index": max(indices) if indices else None,
                "first_missing_index": first_missing,
                "last_files": [item.name for item in pngs[-5:]],
            }
        )
    mp4s = sorted(result_dir.rglob("*.mp4"))
    return {
        "result_dir_exists": result_dir.exists(),
        "frame_writer_summary": frame_writer_summary,
        "png_dirs": png_dirs,
        "mp4_files": [str(item) for item in mp4s],
    }


def _resolution_max_width(resolution: str) -> str | None:
    normalized = (resolution or "").strip().lower()
    if normalized in {"", "source", "native", "original", "auto"}:
        return None
    presets = {
        "480p": "854",
        "540p": "960",
        "720p": "1280",
        "1080p": "1920",
    }
    if normalized in presets:
        return presets[normalized]
    if normalized.endswith("p") and normalized[:-1].isdigit():
        height = int(normalized[:-1])
        width = int(round(height * 16 / 9))
        return str(width if width % 2 == 0 else width + 1)
    if normalized.isdigit():
        return normalized
    return None


def _target_output_fps(*, args, source_video: Path) -> float | None:
    explicit = _parse_positive_float(args.target_fps)
    if explicit:
        return explicit
    if _parse_bool(args.use_source_fps, True):
        return _probe_frame_rate(source_video)
    return None


def _target_duration_seconds(audio_path: Path, video_path: Path) -> float | None:
    durations = [_probe_format_duration(audio_path), _probe_format_duration(video_path)]
    durations = [duration for duration in durations if duration and duration > 0]
    if not durations:
        return None
    return max(durations)


def _pad_video_stream_to_duration(
    produced: Path,
    *,
    target_duration_seconds: float | None,
    temp_dir: Path,
    pad_mode: str,
) -> Path:
    if not target_duration_seconds:
        return produced
    normalized_pad_mode = (pad_mode or "").strip().lower()
    if normalized_pad_mode in {"none", "off", "disabled", "trim"}:
        return produced

    video_duration = _probe_stream_duration(produced, "v:0") or _probe_format_duration(produced)
    if not video_duration or video_duration + 0.05 >= target_duration_seconds:
        return produced

    fixed = temp_dir / "lipsync-duration-fixed.mp4"
    pad_seconds = max(target_duration_seconds - video_duration, 0.0)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(produced),
            "-vf",
            f"tpad=stop_mode=clone:stop_duration={pad_seconds:.3f}",
            "-t",
            f"{target_duration_seconds:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(fixed),
        ],
        check=True,
    )
    return fixed


def _validate_musetalk_temporal_output(
    produced: Path,
    *,
    expected_duration_seconds: float | None,
    expected_fps: float | None,
    stage: str,
    allow_static: bool = False,
) -> dict:
    raw_duration = _probe_stream_duration(produced, "v:0") or _probe_format_duration(produced)
    raw_fps = _probe_frame_rate(produced)
    raw_frame_count = _probe_frame_count(produced)
    expected_frame_count = _expected_frame_count(expected_duration_seconds, expected_fps)
    freeze_report = _detect_freeze(produced)
    report = {
        "stage": stage,
        "raw_output": {
            "raw_output_duration_ms": _milliseconds(raw_duration),
            "raw_output_frame_count": raw_frame_count,
            "raw_output_fps": raw_fps,
            "expected_duration_ms": _milliseconds(expected_duration_seconds),
            "expected_frame_count": expected_frame_count,
            **freeze_report,
        },
        "frame_writer_debug": _read_frame_writer_debug_sidecar(produced),
    }

    failure_reasons = []
    if _is_short_output(
        raw_duration=raw_duration,
        raw_frame_count=raw_frame_count,
        expected_duration=expected_duration_seconds,
        expected_frame_count=expected_frame_count,
    ):
        failure_reasons.append("raw output is shorter than expected")
    if freeze_report["freeze_detected"] and not allow_static:
        failure_reasons.append("raw output contains frozen/static frames")

    if failure_reasons:
        report["failure_reasons"] = failure_reasons
        message = json.dumps(report, ensure_ascii=False, sort_keys=True)
        raise SystemExit(f"MuseTalk temporal validation failed: {message}")
    return report


def _is_short_output(
    *,
    raw_duration: float | None,
    raw_frame_count: int | None,
    expected_duration: float | None,
    expected_frame_count: int | None,
) -> bool:
    tolerance_frames = _env_int("MUSETALK_SHORT_OUTPUT_TOLERANCE_FRAMES", 5)
    tolerance_seconds = _env_float("MUSETALK_SHORT_OUTPUT_TOLERANCE_SECONDS", 0.20)
    if expected_duration and raw_duration and raw_duration + tolerance_seconds < expected_duration:
        return True
    if expected_frame_count and raw_frame_count and raw_frame_count + tolerance_frames < expected_frame_count:
        return True
    return False


def _detect_freeze(path: Path) -> dict:
    frame_width = _env_int("MUSETALK_FREEZE_DETECT_WIDTH", 160)
    frame_height = _env_int("MUSETALK_FREEZE_DETECT_HEIGHT", 90)
    static_threshold = _env_float("MUSETALK_FREEZE_ADJACENT_MAD_THRESHOLD", 0.05)
    warning_ratio_threshold = _env_float("MUSETALK_FREEZE_STATIC_RATIO_WARNING_THRESHOLD", 0.30)
    fail_ratio_threshold = _env_float("MUSETALK_FREEZE_STATIC_RATIO_FAIL_THRESHOLD", 0.40)
    min_run_frames = _env_int("MUSETALK_FREEZE_MIN_RUN_FRAMES", 50)
    frame_size = frame_width * frame_height
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-an",
        "-vf",
        f"scale={frame_width}:{frame_height}:flags=bicubic,format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    result = subprocess.run(command, check=False, capture_output=True)
    if result.returncode != 0:
        return {
            "freeze_detected": False,
            "freeze_start_frame": None,
            "freeze_start_ms": None,
            "adjacent_static_frame_ratio": None,
            "overall_static_ratio": None,
            "speaker_static_ratio": None,
            "intro_static_ratio": None,
            "outro_static_ratio": None,
            "longest_static_run": None,
            "static_validation_status": "unknown",
            "freeze_detection_error": result.stderr.decode("utf-8", "replace").strip(),
        }

    payload = result.stdout
    frame_count = len(payload) // frame_size
    if frame_count < 2:
        return {
            "freeze_detected": False,
            "freeze_start_frame": None,
            "freeze_start_ms": None,
            "adjacent_static_frame_ratio": 0.0,
            "overall_static_ratio": 0.0,
            "speaker_static_ratio": 0.0,
            "intro_static_ratio": 0.0,
            "outro_static_ratio": 0.0,
            "longest_static_run": 0,
            "static_validation_status": "pass",
        }

    static_flags: list[bool] = []
    previous = memoryview(payload[:frame_size])
    for index in range(1, frame_count):
        current = memoryview(payload[index * frame_size : (index + 1) * frame_size])
        total_delta = 0
        for pixel_index in range(frame_size):
            total_delta += abs(current[pixel_index] - previous[pixel_index])
        mean_delta = total_delta / frame_size
        static_flags.append(mean_delta < static_threshold)
        previous = current

    static_ratio = sum(static_flags) / len(static_flags)
    speaker_flags = _speaker_candidate_flags(static_flags)
    speaker_freeze_start = _first_static_run_start(speaker_flags, min_run_frames)
    overall_freeze_start = _first_static_run_start(static_flags, min_run_frames)
    longest_static_run = _longest_static_run(speaker_flags)
    overall_longest_static_run = _longest_static_run(static_flags)
    section_ratios = _section_static_ratios(static_flags)
    fps = _probe_frame_rate(path) or 25.0
    freeze_start_frame = speaker_freeze_start
    freeze_detected = static_ratio > fail_ratio_threshold or speaker_freeze_start is not None
    if freeze_detected:
        validation_status = "fail"
    elif static_ratio > warning_ratio_threshold:
        validation_status = "warning"
    else:
        validation_status = "pass"
    return {
        "freeze_detected": freeze_detected,
        "freeze_start_frame": freeze_start_frame,
        "freeze_start_ms": int((freeze_start_frame / fps) * 1000) if freeze_start_frame is not None and fps else None,
        "overall_freeze_start_frame": overall_freeze_start,
        "adjacent_static_frame_ratio": round(static_ratio, 6),
        "overall_static_ratio": round(static_ratio, 6),
        "speaker_static_ratio": section_ratios["speaker_static_ratio"],
        "intro_static_ratio": section_ratios["intro_static_ratio"],
        "outro_static_ratio": section_ratios["outro_static_ratio"],
        "longest_static_run": longest_static_run,
        "overall_longest_static_run": overall_longest_static_run,
        "static_validation_status": validation_status,
        "freeze_threshold": {
            "adjacent_mad": static_threshold,
            "static_ratio_warning": warning_ratio_threshold,
            "static_ratio_fail": fail_ratio_threshold,
            "min_run_frames": min_run_frames,
        },
    }


def _longest_static_run(static_flags: list[bool]) -> int:
    longest = 0
    run = 0
    for is_static in static_flags:
        if is_static:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return longest


def _section_static_ratios(static_flags: list[bool]) -> dict:
    if not static_flags:
        return {
            "intro_static_ratio": 0.0,
            "speaker_static_ratio": 0.0,
            "outro_static_ratio": 0.0,
        }
    section_size = max(1, int(round(len(static_flags) * 0.2)))
    intro_flags = static_flags[:section_size]
    outro_flags = static_flags[-section_size:]
    speaker_flags = _speaker_candidate_flags(static_flags) or static_flags[section_size:-section_size] or static_flags
    return {
        "intro_static_ratio": round(sum(intro_flags) / len(intro_flags), 6),
        "speaker_static_ratio": round(sum(speaker_flags) / len(speaker_flags), 6),
        "outro_static_ratio": round(sum(outro_flags) / len(outro_flags), 6),
    }


def _speaker_candidate_flags(static_flags: list[bool]) -> list[bool]:
    min_non_speaker_run = _env_int("MUSETALK_SPEAKER_STATIC_EXCLUDE_RUN_FRAMES", 10)
    speaker_flags: list[bool] = []
    index = 0
    while index < len(static_flags):
        if not static_flags[index]:
            speaker_flags.append(False)
            index += 1
            continue
        run_start = index
        while index < len(static_flags) and static_flags[index]:
            index += 1
        run = index - run_start
        if run < min_non_speaker_run:
            speaker_flags.extend([True] * run)
    return speaker_flags


def _first_static_run_start(static_flags: list[bool], min_run_frames: int) -> int | None:
    run = 0
    for index, is_static in enumerate(static_flags):
        if is_static:
            run += 1
            if run >= min_run_frames:
                return index - run + 1
        else:
            run = 0
    return None


def _write_metadata_sidecar(output_video: Path, temporal_report: dict) -> None:
    sidecar = Path(f"{output_video}.metadata.json")
    sidecar.write_text(json.dumps({"temporal_validation": temporal_report}, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_frame_writer_debug_sidecar(output_video: Path, debug_report: dict) -> None:
    sidecar = Path(f"{output_video}.frame_writer_debug.json")
    sidecar.write_text(json.dumps(debug_report, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_frame_writer_debug_sidecar(output_video: Path) -> dict:
    sidecar = Path(f"{output_video}.frame_writer_debug.json")
    if not sidecar.exists():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def _normalize_output_fps(produced: Path, *, target_fps: float | None, temp_dir: Path) -> Path:
    if not target_fps:
        return produced
    current_fps = _probe_frame_rate(produced)
    if current_fps and abs(current_fps - target_fps) < 0.01:
        return produced

    fixed = temp_dir / "lipsync-fps-fixed.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(produced),
            "-filter:v",
            f"fps=fps={target_fps:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(fixed),
        ],
        check=True,
    )
    return fixed


def _apply_quality_preset(produced: Path, *, quality_preset: str, source_video: Path, temp_dir: Path) -> Path:
    normalized = (quality_preset or "").strip().lower()
    if normalized in {"", "current", "musetalk-default", "raw", "no-reencode"}:
        return produced

    video_bitrate = _target_video_bitrate(normalized, source_video)
    crf = _target_crf(normalized)
    fixed = temp_dir / "lipsync-quality-fixed.mp4"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(produced),
        "-c:v",
        "libx264",
        "-preset",
        "slow" if normalized in {"low-crf", "high-quality", "source-fps-high-bitrate"} else "medium",
    ]
    if video_bitrate:
        command.extend(
            [
                "-b:v",
                video_bitrate,
                "-minrate",
                video_bitrate,
                "-maxrate",
                video_bitrate,
                "-bufsize",
                _double_bitrate(video_bitrate),
                "-x264-params",
                "nal-hrd=cbr:force-cfr=1",
            ]
        )
    else:
        command.extend(["-crf", str(crf)])
    command.extend(["-pix_fmt", "yuv420p", "-c:a", "copy", str(fixed)])
    subprocess.run(command, check=True)
    return fixed


def _target_crf(quality_preset: str) -> int:
    if quality_preset in {"low-crf", "high-quality", "source-fps-high-bitrate"}:
        return 18
    return 20


def _target_video_bitrate(quality_preset: str, source_video: Path) -> str | None:
    if quality_preset in {"high-bitrate", "source-fps-high-bitrate", "source-bitrate", "cbr_1500k_source_fps"}:
        if quality_preset == "cbr_1500k_source_fps":
            return "1500k"
        source_bitrate = _probe_video_bitrate(source_video)
        if source_bitrate:
            # Cap extreme phone/source bitrates but stay far above MuseTalk's default tiny output.
            target_kbps = max(1500, min(int(source_bitrate / 1000), 5000))
            return f"{target_kbps}k"
        return "2500k"
    return None


def _double_bitrate(value: str) -> str:
    if value.endswith("k") and value[:-1].isdigit():
        return f"{int(value[:-1]) * 2}k"
    return value


def _probe_video_bitrate(path: Path) -> int | None:
    if not path.exists():
        return None
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=bit_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return int(float(result.stdout.strip().splitlines()[0]))
    except (IndexError, ValueError):
        return None


def _probe_frame_count(path: Path) -> int | None:
    if not path.exists():
        return None
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_frames",
        "-show_entries",
        "stream=nb_read_frames",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    value = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    try:
        return int(value)
    except ValueError:
        return None


def _probe_format_duration(path: Path) -> float | None:
    return _probe_duration(path, ["-show_entries", "format=duration"])


def _probe_stream_duration(path: Path, stream_selector: str) -> float | None:
    return _probe_duration(path, ["-select_streams", stream_selector, "-show_entries", "stream=duration"])


def _probe_frame_rate(path: Path) -> float | None:
    if not path.exists():
        return None
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return _parse_rate(result.stdout.strip())


def _probe_duration(path: Path, entries: list[str]) -> float | None:
    if not path.exists():
        return None
    command = [
        "ffprobe",
        "-v",
        "error",
        *entries,
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    value = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    try:
        return float(value)
    except ValueError:
        return None


def _use_float16(device: str) -> bool:
    value = (os.getenv("MUSETALK_USE_FLOAT16") or "").strip().lower()
    if value:
        return value in {"1", "true", "yes", "on"}
    return device.lower() not in {"cpu", "none"}


def _parse_bool(value: str, default: bool) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def _parse_positive_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_rate(value: str) -> float | None:
    if not value:
        return None
    try:
        numerator, denominator = value.split("/")
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else None
    except ValueError:
        return _parse_positive_float(value)


def _expected_frame_count(duration_seconds: float | None, fps: float | None) -> int | None:
    if not duration_seconds or not fps:
        return None
    return int(round(duration_seconds * fps))


def _milliseconds(duration_seconds: float | None) -> int | None:
    return int(round(duration_seconds * 1000)) if duration_seconds is not None else None


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def _env_or_arg_float(value: str, env_name: str, default: float) -> float:
    raw = (value or os.getenv(env_name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _chunk_mode_enabled(value: str) -> bool:
    normalized = (value or os.getenv("MUSETALK_CHUNK_MODE") or "enabled").strip().lower()
    return normalized in {"1", "true", "yes", "on", "enabled", "chunk", "chunks"}


if __name__ == "__main__":
    main()
