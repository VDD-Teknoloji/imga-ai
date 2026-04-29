"""Turkish-aware text normalization utilities.

Python's str.lower() does not handle Turkish 'İ' correctly:
'İ'.lower() returns 'i̇' (i + COMBINING DOT ABOVE, length 2),
which breaks substring matching against expected lowercase keywords.

normalize_turkish() applies Turkish-specific I/İ → i/ı mapping before
lowercasing and NFC-composes the result so the output is suitable for
substring matching against pre-lowercased keyword frozensets.
"""

from __future__ import annotations

import unicodedata
from typing import Final

# Turkish-specific case mapping applied BEFORE str.lower() so the
# combining-dot pitfall never appears.
_TR_LOWER_MAP: Final[dict[str, str]] = {
    "İ": "i",  # U+0130 LATIN CAPITAL LETTER I WITH DOT ABOVE -> ascii i
    "I": "ı",  # U+0049 LATIN CAPITAL LETTER I             -> dotless i
}


def normalize_turkish(text: str) -> str:
    """Normalize Turkish text for keyword matching.

    Steps:
        1. Apply Turkish-specific I/İ -> i/ı substitutions
        2. Lowercase remaining characters with str.lower()
        3. NFC-normalize to compose any combining characters

    Returns lowercase text safe for substring matching against the
    canonical Turkish keyword frozensets.
    """
    for upper, lower in _TR_LOWER_MAP.items():
        text = text.replace(upper, lower)
    text = text.lower()
    return unicodedata.normalize("NFC", text)
