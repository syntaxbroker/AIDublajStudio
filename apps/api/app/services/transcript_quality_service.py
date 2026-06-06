from __future__ import annotations

import re
from statistics import mean


class TranscriptQualityService:
    warning_threshold = 0.62

    def score(self, segments: list) -> float | None:
        if not segments:
            return None

        segment_scores = [self._segment_score(segment) for segment in segments]
        return round(mean(segment_scores), 2) if segment_scores else None

    def warning(self, segments: list) -> dict | None:
        score = self.score(segments)
        if score is None or score >= self.warning_threshold:
            return None
        return {
            "code": "LOW_TRANSCRIPT_QUALITY",
            "message": "Transcript quality is low; translation may sound unnatural until ASR is improved or reviewed.",
            "transcript_quality_score": score,
            "threshold": self.warning_threshold,
        }

    def _segment_score(self, segment) -> float:
        metadata = dict(getattr(segment, "metadata_json", None) or {})
        components = [
            self._confidence_score(getattr(segment, "confidence", None)),
            self._avg_logprob_score(metadata.get("avg_logprob")),
            self._compression_score(metadata.get("compression_ratio")),
            self._speech_score(metadata.get("no_speech_prob")),
            self._text_score(getattr(segment, "text", "") or ""),
        ]
        return max(0.0, min(1.0, mean(components)))

    def _confidence_score(self, value) -> float:
        if value is None:
            return 0.55
        return max(0.0, min(1.0, float(value)))

    def _avg_logprob_score(self, value) -> float:
        if value is None:
            return 0.55
        # Whisper avg_logprob is usually near 0 for strong segments and below -1 for weak ones.
        return max(0.0, min(1.0, (float(value) + 1.2) / 1.2))

    def _compression_score(self, value) -> float:
        if value is None:
            return 0.7
        compression = float(value)
        if compression <= 2.2:
            return 1.0
        if compression >= 3.2:
            return 0.0
        return round(1.0 - (compression - 2.2), 3)

    def _speech_score(self, value) -> float:
        if value is None:
            return 0.75
        return max(0.0, min(1.0, 1.0 - float(value)))

    def _text_score(self, text: str) -> float:
        words = re.findall(r"\w+", text, flags=re.UNICODE)
        if not words:
            return 0.0
        short_word_ratio = sum(1 for word in words if len(word) <= 2) / len(words)
        repeated_token_ratio = 1.0 - (len(set(word.casefold() for word in words)) / len(words))
        long_gibberish_ratio = sum(1 for word in words if self._looks_noisy(word)) / len(words)
        penalty = min(0.7, short_word_ratio * 0.25 + repeated_token_ratio * 0.25 + long_gibberish_ratio * 0.5)
        return round(1.0 - penalty, 3)

    def _looks_noisy(self, word: str) -> bool:
        if len(word) < 9:
            return False
        vowels = sum(1 for character in word.casefold() if character in "aeiouıöü")
        return vowels / len(word) < 0.25
