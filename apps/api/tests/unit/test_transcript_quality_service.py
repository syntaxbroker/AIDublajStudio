from types import SimpleNamespace

from app.services.transcript_quality_service import TranscriptQualityService


def test_transcript_quality_scores_good_segments_high():
    service = TranscriptQualityService()
    segments = [
        SimpleNamespace(
            text="Znam da te nervira sto tvoj novac stoji na racunu.",
            confidence=0.94,
            metadata_json={"avg_logprob": -0.15, "compression_ratio": 1.2, "no_speech_prob": 0.02},
        )
    ]

    assert service.score(segments) >= 0.9
    assert service.warning(segments) is None


def test_transcript_quality_warns_for_low_confidence_noise():
    service = TranscriptQualityService()
    segments = [
        SimpleNamespace(
            text="xx qqq brrr tsk njvzzzzzz",
            confidence=0.25,
            metadata_json={"avg_logprob": -1.3, "compression_ratio": 3.4, "no_speech_prob": 0.5},
        )
    ]

    warning = service.warning(segments)

    assert warning
    assert warning["code"] == "LOW_TRANSCRIPT_QUALITY"
