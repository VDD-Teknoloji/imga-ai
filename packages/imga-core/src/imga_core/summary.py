"""Heuristic keyword-based one-line summary generator.

Mirrors legacy/app.py:241-312. Produces an emoji-prefixed comma-joined list
of detected concept tags / pain words.
"""

from __future__ import annotations

import re
from typing import Final

from imga_core.lexicons import (
    CRITICAL_KEYWORDS,
    TIER1_SENTIMENT,
    TIER2_ISSUES,
    TIER3_FAILURES,
)

_EMAIL_NOISE_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in (
        r"Sent from my iPhone",
        r"Sent from my Android",
        r"On\s.*wrote:",
        r"Tarihinde\s.*yazdı:",
        r"From:\s",
        r"Kimden:\s",
        r"Subject:\s",
        r"Konu:\s",
        r"Saygılarımızla",
        r"İyi çalışmalar",
        r"LC\s?Waikiki\sMüşteri\sHizmetleri",
        r"Müşteri\sHizmetleri",
        r"https?://\S+",
        r"\bMERHABALAR?\b",
        r"\bSAYIN\sYETKİLİ\b",
        r"\bTEŞEKKÜRLER\b",
    )
]

# Patterns that are headers/greetings: remove the match in place but keep the rest.
_HEADER_TOKENS: Final[tuple[str, ...]] = ("MERHABA", "SAYIN", "SUBJECT", "KONU")

_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"\w+", re.UNICODE)
_SUMMARY_STOPWORDS: Final[frozenset[str]] = frozenset({"tarihinde", "olarak", "kadar"})

_CONCEPT_MAPPING: Final[dict[str, tuple[str, ...]]] = {
    "İletişim Sorunu": (
        "aramadılar",
        "ulaşamadım",
        "cevap yok",
        "açmıyor",
        "muhatap",
        "dönüş yapmadı",
        "kapattı",
        "ulaşılmıyor",
        "numaramı bıraktım",
        "telefona cevap",
    ),
    "İade/Ücret Sorunu": (
        "iade",
        "ücret",
        "para",
        "hesap",
        "yatmadı",
        "tutar",
    ),
    "Teslimat Gecikmesi": (
        "kargo",
        "gelmedi",
        "teslim",
        "gecikti",
        "bekliyorum",
        "ulaşmadı",
    ),
}


def generate_heuristic_summary(text: str) -> str:
    """Produce a short bullet-style summary from extracted keywords."""
    if not text:
        return ""

    cleaned = _strip_email_noise(text)
    lower = cleaned.lower()
    found: list[str] = []
    seen: set[str] = set()

    def _push(item: str) -> None:
        if item not in seen:
            seen.add(item)
            found.append(item)

    for word in CRITICAL_KEYWORDS:
        if word in lower:
            _push("🚨 " + word.upper())

    for concept, keywords in _CONCEPT_MAPPING.items():
        if any(kw in lower for kw in keywords):
            _push(concept)

    for word in TIER1_SENTIMENT:
        if word in lower:
            _push(word.title())
    for word in TIER2_ISSUES:
        if word in lower:
            _push(word.title())
    for word in TIER3_FAILURES:
        if word in lower:
            _push(word.title())

    if found:
        return "📝 " + ", ".join(found[:5])

    words = [
        w for w in _WORD_PATTERN.findall(cleaned)
        if len(w) > 4 and w.lower() not in _SUMMARY_STOPWORDS
    ]
    longest = sorted(set(words), key=len, reverse=True)[:4]
    return "📝 " + ", ".join(longest) if longest else ""


def _strip_email_noise(text: str) -> str:
    """Remove signature/header noise; preserve body content."""
    cleaned = text
    for pattern in _EMAIL_NOISE_PATTERNS:
        match = pattern.search(cleaned)
        if match is None:
            continue
        if any(token in pattern.pattern.upper() for token in _HEADER_TOKENS):
            cleaned = pattern.sub(" ", cleaned)
        else:
            cleaned = cleaned[: match.start()]
    cleaned = cleaned.strip()
    if not cleaned:
        cleaned = text[:100]
    return cleaned
