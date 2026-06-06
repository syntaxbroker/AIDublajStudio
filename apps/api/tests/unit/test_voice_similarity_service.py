import math
import wave
from pathlib import Path

from app.services.voice_similarity_service import VoiceSimilarityService


def _write_sine(path: Path, *, frequency: float, duration_s: float = 1.0, sample_rate: int = 16000) -> None:
    frame_count = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            value = int(math.sin(2 * math.pi * frequency * index / sample_rate) * 12000)
            frames.extend(value.to_bytes(2, byteorder="little", signed=True))
        wav_file.writeframes(bytes(frames))


def test_voice_similarity_scores_identical_audio_high(tmp_path: Path):
    reference = tmp_path / "reference.wav"
    generated = tmp_path / "generated.wav"
    _write_sine(reference, frequency=180)
    _write_sine(generated, frequency=180)

    result = VoiceSimilarityService().compare(reference, generated)

    assert result["voice_similarity_score"] >= 0.95
    assert result["cosine_similarity"] >= 0.99
    assert result["reference_sample_quality"]["voiced_ratio"] > 0.9


def test_voice_similarity_detects_pitch_and_spectral_change(tmp_path: Path):
    reference = tmp_path / "reference.wav"
    generated = tmp_path / "generated.wav"
    _write_sine(reference, frequency=160)
    _write_sine(generated, frequency=300)

    result = VoiceSimilarityService().compare(reference, generated)

    assert result["voice_similarity_score"] < 0.95
    assert result["pitch_statistics"]["absolute_mean_delta_hz"] > 50
    assert result["spectral_distance"] > 0
