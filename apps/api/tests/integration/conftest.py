import os
from pathlib import Path

import httpx
import psycopg
import pytest


BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://aidublaj:aidublaj@postgres:5432/aidublaj").replace(
    "postgresql+psycopg://", "postgresql://"
)
STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", "/workspace/storage/projects"))
VALID_SAMPLE_VIDEO_PATH = Path(os.getenv("VALID_SAMPLE_VIDEO_PATH", "/workspace/storage/tmp/sprint2-sample.mp4"))


@pytest.fixture(scope="session")
def client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=120)


@pytest.fixture(scope="session")
def auth_headers(client: httpx.Client) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"email": "editor@example.com", "password": "editor123"},
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def temp_video_file(tmp_path: Path) -> Path:
    target = tmp_path / "sample.mp4"
    target.write_bytes(b"fake mp4 payload")
    return target


@pytest.fixture
def exotic_filename_video(tmp_path: Path) -> Path:
    target = tmp_path / "Turkce_Ornek_Dosya_Cok_Uzun_Isim_😀_şğüçıö_video_test_asset.mp4"
    target.write_bytes(b"fake mp4 payload")
    return target


@pytest.fixture(scope="session")
def db_conn():
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn


@pytest.fixture(scope="session")
def valid_sample_video_file() -> Path:
    if not VALID_SAMPLE_VIDEO_PATH.exists():
        raise FileNotFoundError(f"Valid sample video not found at {VALID_SAMPLE_VIDEO_PATH}")
    return VALID_SAMPLE_VIDEO_PATH


@pytest.fixture(scope="session")
def storage_root() -> Path:
    return STORAGE_ROOT
