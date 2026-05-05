"""Word cloud generator for the /insights wordcloud tab.

Sprint 8.3.9. Tokenises review texts, applies a Türkçe stop-word
filter, computes per-token frequencies + sentiment skew, optionally
adds bigrams. NO stemming — Türkçe stemming via naive suffix-strip
produces wrong roots; a real morphology layer belongs in imga-core,
not here.

The package is structured so the stopword list (~200 words) lives
in its own module and the algorithmic code (tokenise / aggregate)
in ``generator``. ``__init__`` re-exports the public surface.
"""

from __future__ import annotations

from imga_api.services.word_cloud.generator import (
    CACHE_TTL_SECONDS,
    WordCloudGenerator,
    tokenize,
)
from imga_api.services.word_cloud.turkish_stopwords import TURKISH_STOPWORDS

__all__ = [
    "CACHE_TTL_SECONDS",
    "TURKISH_STOPWORDS",
    "WordCloudGenerator",
    "tokenize",
]
