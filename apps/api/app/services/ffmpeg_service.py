import subprocess
from pathlib import Path


class FFmpegService:
    def generate_thumbnail(self, source_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vf",
            "thumbnail,scale=640:-1",
            "-frames:v",
            "1",
            str(output_path),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)

    def generate_proxy(self, source_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vf",
            "scale=-2:720:force_original_aspect_ratio=decrease",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output_path),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)

    def extract_waveform_audio(self, source_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)

    def extract_audio_segment(self, source_path: Path, output_path: Path, start_ms: int, end_ms: int, sample_rate: int = 22050) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration_seconds = max(end_ms - start_ms, 1) / 1000
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(start_ms, 0) / 1000:.3f}",
            "-i",
            str(source_path),
            "-t",
            f"{duration_seconds:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            str(output_path),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)

    def mix_audio_segments(self, segments: list[dict], output_path: Path, total_duration_ms: int, sample_rate: int = 22050) -> None:
        if not segments:
            raise ValueError("Audio mix requires at least one segment")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        base_duration_seconds = max(total_duration_ms, 1) / 1000
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-t",
            f"{base_duration_seconds:.3f}",
            "-i",
            f"anullsrc=r={sample_rate}:cl=mono",
        ]

        for segment in segments:
            command.extend(["-i", str(segment["source_path"])])

        filter_parts: list[str] = []
        mix_inputs = ["[0:a]"]
        for index, segment in enumerate(segments, start=1):
            delay_ms = max(int(segment["start_ms"]), 0)
            clip_duration_seconds = max(int(segment["clip_duration_ms"]), 1) / 1000
            label = f"s{index}"
            filter_parts.append(
                f"[{index}:a]atrim=0:{clip_duration_seconds:.3f},adelay={delay_ms}|{delay_ms}[{label}]"
            )
            mix_inputs.append(f"[{label}]")

        filter_parts.append(
            "".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=longest:normalize=0[mix]"
        )
        command.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[mix]",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                str(output_path),
            ]
        )
        subprocess.run(command, check=True, capture_output=True, text=True)

    def render_video_with_audio(self, video_path: Path, audio_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
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
            "-vf",
            "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ac",
            "1",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
