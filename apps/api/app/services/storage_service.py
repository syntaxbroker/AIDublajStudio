import hashlib
import json
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings


class StorageService:
    def __init__(self) -> None:
        self.root = Path(get_settings().storage_root)

    def project_dir(self, storage_key: str) -> Path:
        return self.root / storage_key

    def ensure_project_structure(self, storage_key: str) -> Path:
        base = self.project_dir(storage_key)
        for child in [
            "source",
            "metadata",
            "thumbnails",
            "proxies",
            "audio",
            "transcripts",
            "translations",
            "tts",
            "lipsync",
            "renders",
            "waveforms",
            "versions",
            "snapshots",
        ]:
            (base / child).mkdir(parents=True, exist_ok=True)
        return base

    def save_source_video(self, storage_key: str, upload: UploadFile, artifact_id: str) -> tuple[str, int, str]:
        base = self.ensure_project_structure(storage_key)
        suffix = Path(upload.filename or "").suffix
        target = base / "source" / f"{artifact_id}{suffix}"
        sha256 = hashlib.sha256()
        size = 0

        with target.open("wb") as output:
            while chunk := upload.file.read(1024 * 1024):
                output.write(chunk)
                sha256.update(chunk)
                size += len(chunk)

        relative_path = target.relative_to(self.root).as_posix()
        return relative_path, size, sha256.hexdigest()

    def absolute_path(self, relative_path: str) -> Path:
        return self.root / relative_path

    def write_bytes(self, storage_key: str, subdir: str, file_name: str, content: bytes) -> tuple[str, int, str]:
        base = self.ensure_project_structure(storage_key)
        target = base / subdir / file_name
        target.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        relative_path = target.relative_to(self.root).as_posix()
        return relative_path, len(content), checksum

    def write_json(self, storage_key: str, subdir: str, file_name: str, payload: dict) -> tuple[str, int, str]:
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        return self.write_bytes(storage_key, subdir, file_name, content)

    def exists(self, relative_path: str) -> bool:
        return self.absolute_path(relative_path).exists()

    def delete_relative_path(self, relative_path: str) -> None:
        target = self.root / relative_path
        if target.exists():
            target.unlink()
