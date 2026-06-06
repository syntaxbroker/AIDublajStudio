from app.services.translation_adaptation import (
    adapt_turkish_text_preserving_semantics,
    estimate_turkish_speech_duration_ms,
    fit_turkish_text_to_duration,
    semantic_similarity_score,
)


def test_fit_turkish_text_to_duration_keeps_output_under_target():
    text = "Gidip gidemezsek, yol boyunca tanışalım, görelim bakalım."
    fitted = fit_turkish_text_to_duration(text, 2500)

    assert fitted
    assert estimate_turkish_speech_duration_ms(fitted) <= 2500


def test_fit_turkish_text_to_duration_collapses_repeated_words():
    fitted = fit_turkish_text_to_duration("geliyor geliyor geliyor.", 2000)

    assert fitted == "geliyor."


def test_adaptation_rejects_semantic_corruption():
    faithful = "Gunluk cekim limitini astigin icin paran hesapta bekliyor."
    result = adapt_turkish_text_preserving_semantics(faithful, 700)

    assert result["adaptation_rejected"] is True
    assert result["adapted_text"] == faithful
    assert result["semantic_similarity_score"] == 1.0
    assert result["rejected_semantic_similarity_score"] < result["semantic_similarity_threshold"]


def test_semantic_similarity_allows_close_adaptation():
    faithful = "Paran hesapta bekliyor."
    adapted = "Paran hesapta bekliyor."

    assert semantic_similarity_score(faithful, adapted) == 1.0
