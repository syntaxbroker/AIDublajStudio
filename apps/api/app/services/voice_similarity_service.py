from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np


class VoiceSimilarityService:
    def analyze(self, path: Path) -> dict:
        sample_rate, audio = self._read_wav(path)
        metrics = self._analyze_audio(sample_rate, audio)
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            frame_count = wav_file.getnframes()
            duration_seconds = frame_count / sample_rate if sample_rate else 0.0
        return {
            "duration_seconds": round(duration_seconds, 3),
            "sample_rate": sample_rate,
            "channels": channels,
            "rms_level": round(metrics["rms_dbfs"], 2),
            "rms_dbfs": round(metrics["rms_dbfs"], 2),
            "speech_ratio": round(metrics["voiced_ratio"], 4),
            "voiced_ratio": round(metrics["voiced_ratio"], 4),
            "snr_estimate": round(metrics["snr_db"], 2),
            "snr_db": round(metrics["snr_db"], 2),
            "silence_ratio": round(metrics["silence_ratio"], 4),
            "spectral_centroid_hz": round(metrics["spectral_centroid_hz"], 2),
            "pitch_mean_hz": round(metrics["pitch_mean_hz"], 2),
            "pitch_std_hz": round(metrics["pitch_std_hz"], 2),
        }

    def compare(self, reference_path: Path, generated_path: Path) -> dict:
        reference = self._analyze(reference_path)
        generated = self._analyze(generated_path)
        cosine = self._cosine(reference["embedding"], generated["embedding"])
        spectral_distance = abs(reference["spectral_centroid_hz"] - generated["spectral_centroid_hz"]) / 4000
        pitch_distance = abs(reference["pitch_mean_hz"] - generated["pitch_mean_hz"]) / 300
        energy_distance = abs(reference["rms_dbfs"] - generated["rms_dbfs"]) / 30
        embedding_distance = max(0.0, 1.0 - cosine)
        voice_similarity_score = max(
            0.0,
            min(
                1.0,
                (cosine * 0.45)
                + ((1.0 - min(spectral_distance, 1.0)) * 0.25)
                + ((1.0 - min(pitch_distance, 1.0)) * 0.20)
                + ((1.0 - min(energy_distance, 1.0)) * 0.10),
            ),
        )
        return {
            "voice_similarity_score": round(voice_similarity_score, 2),
            "cosine_similarity": round(cosine, 4),
            "speaker_embedding_distance": round(embedding_distance, 4),
            "spectral_distance": round(spectral_distance, 4),
            "pitch_statistics": {
                "reference_mean_hz": round(reference["pitch_mean_hz"], 2),
                "reference_std_hz": round(reference["pitch_std_hz"], 2),
                "generated_mean_hz": round(generated["pitch_mean_hz"], 2),
                "generated_std_hz": round(generated["pitch_std_hz"], 2),
                "absolute_mean_delta_hz": round(abs(reference["pitch_mean_hz"] - generated["pitch_mean_hz"]), 2),
            },
            "reference_sample_quality": {
                "snr_db": round(reference["snr_db"], 2),
                "rms_dbfs": round(reference["rms_dbfs"], 2),
                "voiced_ratio": round(reference["voiced_ratio"], 4),
                "silence_ratio": round(reference["silence_ratio"], 4),
            },
            "generated_audio_metrics": {
                "rms_dbfs": round(generated["rms_dbfs"], 2),
                "voiced_ratio": round(generated["voiced_ratio"], 4),
                "silence_ratio": round(generated["silence_ratio"], 4),
                "spectral_centroid_hz": round(generated["spectral_centroid_hz"], 2),
            },
            "metric_method": "deterministic_acoustic_proxy_v1",
        }

    def _analyze(self, path: Path) -> dict:
        sample_rate, audio = self._read_wav(path)
        return self._analyze_audio(sample_rate, audio)

    def _analyze_audio(self, sample_rate: int, audio: np.ndarray) -> dict:
        if audio.size == 0:
            return self._empty_metrics()
        audio = audio.astype(np.float32)
        peak = float(np.max(np.abs(audio))) or 1e-12
        rms = float(np.sqrt(np.mean(audio * audio)) + 1e-12)
        rms_dbfs = 20 * math.log10(rms)
        frame_size = max(1, int(sample_rate * 0.025))
        hop = max(1, int(sample_rate * 0.010))
        frames = self._frames(audio, frame_size, hop)
        frame_rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12) if frames.size else np.array([rms])
        frame_db = 20 * np.log10(frame_rms + 1e-12)
        silence_ratio = float(np.mean(frame_db < -40))
        voiced_ratio = 1.0 - silence_ratio
        noise = float(np.percentile(frame_rms, 10) + 1e-12)
        signal = float(np.percentile(frame_rms, 90) + 1e-12)
        snr_db = 20 * math.log10(signal / noise) if noise > 0 else 0.0
        spectral_centroid = self._spectral_centroid(audio, sample_rate)
        zcr = float(np.mean(np.abs(np.diff(np.signbit(audio))))) if audio.size > 1 else 0.0
        pitches = self._pitch_values(frames, sample_rate)
        pitch_mean = float(np.mean(pitches)) if pitches else 0.0
        pitch_std = float(np.std(pitches)) if pitches else 0.0
        embedding = np.array(
            [
                max(min((rms_dbfs + 60) / 60, 1.0), 0.0),
                min(peak, 1.0),
                voiced_ratio,
                silence_ratio,
                min(snr_db / 40, 1.0),
                min(spectral_centroid / 5000, 1.0),
                min(zcr / 0.3, 1.0),
                min(pitch_mean / 350, 1.0),
                min(pitch_std / 180, 1.0),
            ],
            dtype=np.float32,
        )
        return {
            "embedding": embedding,
            "rms_dbfs": rms_dbfs,
            "snr_db": snr_db,
            "voiced_ratio": voiced_ratio,
            "silence_ratio": silence_ratio,
            "spectral_centroid_hz": spectral_centroid,
            "pitch_mean_hz": pitch_mean,
            "pitch_std_hz": pitch_std,
        }

    def _read_wav(self, path: Path) -> tuple[int, np.ndarray]:
        with wave.open(str(path), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.readframes(wav_file.getnframes())
        if sample_width == 2:
            audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        elif sample_width == 4:
            audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / float(2**31)
        else:
            audio = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
            audio = ((audio - 128.0) / 128.0).astype(np.float32)
        if channels > 1 and audio.size:
            audio = audio.reshape(-1, channels).mean(axis=1)
        return sample_rate, audio

    def _frames(self, audio: np.ndarray, frame_size: int, hop: int) -> np.ndarray:
        if audio.size < frame_size:
            return audio.reshape(1, -1)
        return np.array([audio[index : index + frame_size] for index in range(0, audio.size - frame_size + 1, hop)])

    def _spectral_centroid(self, audio: np.ndarray, sample_rate: int) -> float:
        window_size = min(2048, max(256, int(sample_rate * 0.05)))
        if audio.size < window_size:
            padded = np.pad(audio, (0, window_size - audio.size))
        else:
            padded = audio[:window_size]
        spectrum = np.abs(np.fft.rfft(padded * np.hanning(window_size))) + 1e-12
        freqs = np.fft.rfftfreq(window_size, 1 / sample_rate)
        return float(np.sum(freqs * spectrum) / np.sum(spectrum))

    def _pitch_values(self, frames: np.ndarray, sample_rate: int) -> list[float]:
        values: list[float] = []
        min_lag = max(1, int(sample_rate / 350))
        max_lag = max(min_lag + 1, int(sample_rate / 70))
        for frame in frames[:200]:
            centered = frame - np.mean(frame)
            if float(np.sqrt(np.mean(centered * centered)) + 1e-12) < 0.01:
                continue
            autocorr = np.correlate(centered, centered, mode="full")[centered.size - 1 :]
            if autocorr.size <= max_lag:
                continue
            lag = int(np.argmax(autocorr[min_lag:max_lag]) + min_lag)
            if lag > 0:
                values.append(float(sample_rate / lag))
        return values

    def _cosine(self, left: np.ndarray, right: np.ndarray) -> float:
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator <= 0:
            return 0.0
        return max(0.0, min(1.0, float(np.dot(left, right) / denominator)))

    def _empty_metrics(self) -> dict:
        return {
            "embedding": np.zeros(9, dtype=np.float32),
            "rms_dbfs": -120.0,
            "snr_db": 0.0,
            "voiced_ratio": 0.0,
            "silence_ratio": 1.0,
            "spectral_centroid_hz": 0.0,
            "pitch_mean_hz": 0.0,
            "pitch_std_hz": 0.0,
        }
