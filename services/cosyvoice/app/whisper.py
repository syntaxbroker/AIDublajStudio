from __future__ import annotations

import torch
import torchaudio


def log_mel_spectrogram(audio: torch.Tensor, n_mels: int = 80) -> torch.Tensor:
    if audio.dim() == 1:
        audio = audio.unsqueeze(0)
    if audio.dim() != 2:
        raise ValueError(f"expected audio tensor with 1 or 2 dimensions, got {audio.dim()}")

    mel_transform = torchaudio.transforms.MelSpectrogram(
        sample_rate=16000,
        n_fft=400,
        win_length=400,
        hop_length=160,
        n_mels=n_mels,
        power=2.0,
        center=True,
    ).to(audio.device)
    mel = mel_transform(audio)
    mel = torch.clamp(mel, min=1e-10).log10()
    mel = torch.maximum(mel, mel.max() - 8.0)
    mel = (mel + 4.0) / 4.0
    return mel
