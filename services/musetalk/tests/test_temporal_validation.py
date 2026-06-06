import sys
from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

import run_musetalk  # noqa: E402


def _make_video(path: Path, source: str, *, duration: float, fps: int = 25) -> None:
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            source,
            "-t",
            f"{duration:.3f}",
            "-r",
            str(fps),
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_temporal_validation_rejects_short_raw_output(tmp_path: Path):
    video = tmp_path / "short.mp4"
    _make_video(video, "testsrc=size=160x90:rate=25", duration=1.0)

    with pytest.raises(SystemExit) as exc_info:
        run_musetalk._validate_musetalk_temporal_output(
            video,
            expected_duration_seconds=5.0,
            expected_fps=25.0,
            stage="raw",
        )

    assert "raw output is shorter than expected" in str(exc_info.value)


def test_temporal_validation_rejects_frozen_raw_output(tmp_path: Path):
    video = tmp_path / "frozen.mp4"
    _make_video(video, "color=c=black:size=160x90:rate=25", duration=5.0)

    with pytest.raises(SystemExit) as exc_info:
        run_musetalk._validate_musetalk_temporal_output(
            video,
            expected_duration_seconds=5.0,
            expected_fps=25.0,
            stage="raw",
        )

    assert "raw output contains frozen/static frames" in str(exc_info.value)


def test_temporal_validation_accepts_full_motion_output(tmp_path: Path):
    video = tmp_path / "motion.mp4"
    _make_video(video, "testsrc=size=160x90:rate=25", duration=5.0)

    report = run_musetalk._validate_musetalk_temporal_output(
        video,
        expected_duration_seconds=5.0,
        expected_fps=25.0,
        stage="raw",
    )

    raw_output = report["raw_output"]
    assert raw_output["raw_output_frame_count"] >= 123
    assert raw_output["expected_frame_count"] == 125
    assert raw_output["freeze_detected"] is False


def test_temporal_validation_warns_on_elevated_static_ratio_without_freeze():
    static_flags = [True] * 17 + [False] * 45
    section_ratios = run_musetalk._section_static_ratios(static_flags)

    assert run_musetalk._longest_static_run(static_flags) == 17
    assert sum(static_flags) / len(static_flags) > 0.20
    assert sum(static_flags) / len(static_flags) <= 0.30
    assert section_ratios["speaker_static_ratio"] < 0.30


def test_temporal_validation_fails_on_long_static_run():
    static_flags = [False] * 5 + [True] * 50 + [False] * 5

    assert run_musetalk._first_static_run_start(static_flags, 50) == 5
    assert run_musetalk._longest_static_run(static_flags) == 50
