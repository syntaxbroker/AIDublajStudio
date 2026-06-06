from __future__ import annotations

import re
from difflib import SequenceMatcher


TURKISH_VOWELS = set("aeiouAEIOU\u0131\u0130\u00f6\u00d6\u00fc\u00dc")
SEMANTIC_SIMILARITY_THRESHOLD = 0.72
TURKISH_STOPWORDS = {
    "bir",
    "bu",
    "da",
    "de",
    "ile",
    "ve",
    "veya",
    "icin",
    "m\u0131",
    "m\u00fc",
    "mu",
    "ne",
    "o",
    "sen",
    "sana",
    "seni",
    "\u015fu",
}


def estimate_turkish_speech_duration_ms(text: str) -> int:
    syllable_count = sum(1 for character in text if character in TURKISH_VOWELS)
    word_count = len(re.findall(r"\w+", text, flags=re.UNICODE))
    if syllable_count <= 0 and word_count <= 0:
        return 0
    estimated_from_syllables = syllable_count * 185
    estimated_from_words = word_count * 360
    return max(estimated_from_syllables, estimated_from_words, 350)


def duration_match_score(source_duration_ms: int, translated_duration_ms: int) -> float:
    if source_duration_ms <= 0 or translated_duration_ms <= 0:
        return 0.0
    ratio = min(source_duration_ms, translated_duration_ms) / max(source_duration_ms, translated_duration_ms)
    return round(ratio, 2)


def max_turkish_syllables_for_duration(duration_ms: int) -> int:
    return max(1, int(duration_ms / 185))


def build_adaptation_metadata(source_duration_ms: int, translated_text: str) -> dict:
    translated_duration_ms = estimate_turkish_speech_duration_ms(translated_text)
    return {
        "source_duration_ms": source_duration_ms,
        "translated_duration_ms": translated_duration_ms,
        "duration_match_score": duration_match_score(source_duration_ms, translated_duration_ms),
    }


def semantic_similarity_score(faithful_text: str, adapted_text: str) -> float:
    faithful_tokens = _meaning_tokens(faithful_text)
    adapted_tokens = _meaning_tokens(adapted_text)
    if not faithful_tokens and not adapted_tokens:
        return 1.0
    if not faithful_tokens or not adapted_tokens:
        return 0.0

    faithful_set = set(faithful_tokens)
    adapted_set = set(adapted_tokens)
    token_recall = len(faithful_set & adapted_set) / len(faithful_set)
    token_precision = len(faithful_set & adapted_set) / len(adapted_set)
    token_score = (token_recall * 0.75) + (token_precision * 0.25)
    sequence_score = SequenceMatcher(None, _normalize_text(faithful_text), _normalize_text(adapted_text)).ratio()
    return round(max(0.0, min(1.0, (token_score * 0.7) + (sequence_score * 0.3))), 2)


def adapt_turkish_text_preserving_semantics(
    faithful_text: str,
    target_duration_ms: int,
    *,
    threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
) -> dict:
    candidate = fit_turkish_text_to_duration(faithful_text, target_duration_ms)
    candidate_score = semantic_similarity_score(faithful_text, candidate)
    if candidate_score < threshold:
        return {
            "adapted_text": faithful_text.strip(),
            "semantic_similarity_score": 1.0,
            "adaptation_rejected": True,
            "rejected_adapted_text": candidate,
            "rejected_semantic_similarity_score": candidate_score,
            "semantic_similarity_threshold": threshold,
        }
    return {
        "adapted_text": candidate,
        "semantic_similarity_score": candidate_score,
        "adaptation_rejected": False,
        "semantic_similarity_threshold": threshold,
    }


def fit_turkish_text_to_duration(text: str, target_duration_ms: int) -> str:
    cleaned = _collapse_repeated_words(text.strip())
    if estimate_turkish_speech_duration_ms(cleaned) <= target_duration_ms:
        return _restore_sentence_punctuation(cleaned, text) if cleaned != text.strip() else cleaned

    words = re.findall(r"\w+|[^\w\s]", cleaned, flags=re.UNICODE)
    content_words = [word for word in words if re.match(r"\w+", word, flags=re.UNICODE)]
    if len(content_words) <= 1:
        return cleaned

    while len(content_words) > 1:
        content_words.pop()
        candidate = " ".join(content_words)
        if estimate_turkish_speech_duration_ms(candidate) <= target_duration_ms:
            return _restore_sentence_punctuation(candidate, cleaned)

    return _restore_sentence_punctuation(content_words[0], cleaned)


def _meaning_tokens(text: str) -> list[str]:
    tokens = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
    return [token for token in tokens if token not in TURKISH_STOPWORDS]


def _normalize_text(text: str) -> str:
    return " ".join(_meaning_tokens(text))


def _collapse_repeated_words(text: str) -> str:
    words = text.split()
    collapsed: list[str] = []
    for word in words:
        normalized = word.strip(".,!?;:").casefold()
        previous = collapsed[-1].strip(".,!?;:").casefold() if collapsed else ""
        if normalized and normalized == previous:
            continue
        collapsed.append(word)
    return " ".join(collapsed)


def _restore_sentence_punctuation(candidate: str, original: str) -> str:
    candidate = candidate.strip(" ,;:")
    if not candidate:
        return original
    if original.strip().endswith("?"):
        return candidate + "?"
    if original.strip().endswith("!"):
        return candidate + "!"
    return candidate + "."
