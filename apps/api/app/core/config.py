from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Dublaj Studio API"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://aidublaj:aidublaj@localhost:5432/aidublaj"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "<CHANGE_ME>"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    storage_root: str = str(Path(__file__).resolve().parents[4] / "storage" / "projects")
    default_admin_email: str = "admin@example.com"
    default_admin_password: str = "admin123"
    default_editor_email: str = "editor@example.com"
    default_editor_password: str = "editor123"
    asr_provider: str = "mock"
    asr_source_language: str = "auto"
    asr_model_size: str = "tiny"
    asr_device: str = "auto"
    asr_compute_type: str = "auto"
    asr_word_timestamps: bool = True
    translation_provider: str = "mock"
    translation_target_language: str = "tr"
    tts_provider: str = "mock"
    tts_voice_name: str = "default"
    tts_clone_mode: str = "auto"
    tts_duration_fit_allow_rewrite: bool = False
    tts_duration_fit_min_semantic_similarity: float = 0.72
    tts_voice_conversion_base_provider: str = "edge_tts"
    tts_voice_conversion_base_voice: str = "tr-TR-AhmetNeural"
    voice_clone_provider: str = "mock"
    voice_conversion_provider: str = "seedvc"
    voice_clone_min_sample_duration_ms: int = 500
    voice_clone_required_duration_ms: int = 20_000
    voice_clone_min_speech_ratio: float = 0.50
    voice_clone_max_silence_ratio: float = 0.50
    voice_clone_min_snr_db: float = 6.0
    voice_clone_min_quality_score: float = 0.50
    lip_sync_provider: str = "mock"
    allow_mock_providers: bool = False
    audio_mix_trim_to_timeline: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_translation_model: str = "qwen2.5:7b"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_translation_model: str = "gpt-4.1-mini"
    diarization_provider: str = "mock"
    pyannote_auth_token: str | None = None
    pyannote_pipeline_name: str = "pyannote/speaker-diarization-3.1"
    edge_tts_voice: str = "tr-TR-AhmetNeural"
    piper_model_path: str | None = None
    cosyvoice_model_path: str | None = None
    cosyvoice_service_url: str | None = None
    cosyvoice_service_timeout_seconds: int = 180
    cosyvoice_model_name: str = "CosyVoice"
    musetalk_service_url: str | None = None
    musetalk_service_timeout_seconds: int = 1800
    musetalk_model_name: str = "MuseTalk"
    musetalk_face_mode: str = "auto"
    musetalk_fps: str | None = None
    musetalk_resolution: str = "source"
    musetalk_batch_size: int = 2
    musetalk_pad_mode: str = "clone"
    musetalk_use_source_fps: bool = True
    musetalk_quality_preset: str = "source-native"
    musetalk_chunk_mode: str = "enabled"
    musetalk_chunk_seconds: float = 2.5
    musetalk_chunk_overlap_ms: int = 160
    f5tts_model_path: str | None = None
    seedvc_repo_dir: str | None = None
    seedvc_python_executable: str = "python"
    seedvc_checkpoint: str | None = None
    seedvc_config: str | None = None
    seedvc_diffusion_steps: int = 25
    seedvc_length_adjust: float = 1.0
    seedvc_inference_cfg_rate: float = 0.7
    seedvc_fp16: bool = True
    seedvc_timeout_seconds: int = 900
    seedvc_cuda_visible_devices: str | None = None
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
