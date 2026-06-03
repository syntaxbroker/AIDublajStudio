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
