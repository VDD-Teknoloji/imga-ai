"""Sprint 8.3.9 — WordCloudGenerator + tokenizer unit tests.

Pure logic — no DB. Verifies the tokeniser handles Türkçe characters,
the stop-word filter removes the obvious enclitics, and the bigram
helper produces adjacent pairs.
"""

from __future__ import annotations

from imga_api.services.word_cloud import TURKISH_STOPWORDS, tokenize
from imga_api.services.word_cloud.generator import bigrams_of


def test_tokenize_lowercases_and_keeps_turkish_letters() -> None:
    """``Çarşamba`` should survive tokenisation and case-fold to
    ``çarşamba`` — naive ASCII strip would lose the ş/ç."""
    tokens = tokenize("Çarşamba günü kargo gelmedi.")
    # All output is lowercase; no token has ASCII-folded letters.
    assert all(t == t.lower() for t in tokens)
    assert "çarşamba" in tokens
    assert "kargo" in tokens
    assert "gelmedi" in tokens


def test_tokenize_filters_stopwords() -> None:
    """Common Türkçe stopwords (``için``, ``ve``, ``ki``) must be
    removed; signal words survive."""
    tokens = tokenize("Kargom için bekledim ve gelmedi ki gerçekten yoruldum.")
    assert "için" not in tokens
    assert "ve" not in tokens
    assert "ki" not in tokens
    assert "kargom" in tokens
    assert "bekledim" in tokens


def test_tokenize_drops_short_and_numeric_tokens() -> None:
    """Tokens shorter than 3 chars are dropped (mostly enclitic
    fragments) along with bare digits."""
    tokens = tokenize("Bu 12 kez 3 ay içinde tekrar oldu.")
    assert "12" not in tokens
    assert "3" not in tokens
    # "bu" is in the stoplist; "ay" is two chars (filtered).
    assert "ay" not in tokens
    # "kez" passes the length filter, but the stopword list excludes it.
    assert "kez" not in tokens


def test_tokenize_handles_punctuation_without_eating_letters() -> None:
    """Punctuation ("!", ".", ",") drops out; tokens stay intact."""
    tokens = tokenize("Müşteri hizmetleri!!! çok iyi, harika.")
    assert "müşteri" in tokens
    assert "hizmetleri" in tokens
    assert "harika" in tokens


def test_bigrams_of_emits_adjacent_pairs() -> None:
    """N tokens → N-1 bigrams in adjacent order."""
    pairs = bigrams_of(["kargo", "gelmedi", "iade", "etmek"])
    assert pairs == ["kargo gelmedi", "gelmedi iade", "iade etmek"]


def test_bigrams_of_returns_empty_when_too_short() -> None:
    assert bigrams_of([]) == []
    assert bigrams_of(["only"]) == []


def test_stopword_set_includes_documented_enclitics() -> None:
    """Regression guard for a future stopword-list edit dropping the
    enclitic forms — the word-cloud quality cratered when ``de`` /
    ``da`` / ``ki`` leaked in during a prototype."""
    for enclitic in ("de", "da", "ki", "mi", "mı", "mu", "için"):
        assert enclitic in TURKISH_STOPWORDS, (
            f"stopword {enclitic!r} missing from list"
        )
