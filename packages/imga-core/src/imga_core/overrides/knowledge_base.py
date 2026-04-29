"""Knowledge-base lookup: exact-match user-corrected labels from training_data.csv."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from imga_core.config import (
    KB_LABEL_COLUMN,
    KB_NEGATIVE_SCORE,
    KB_NEUTRAL_SCORE,
    KB_POSITIVE_SCORE,
    KB_TEXT_COLUMNS,
    LEGACY_LABEL_MAP,
)
from imga_core.models import OverrideHit

_logger = logging.getLogger(__name__)


class KnowledgeBase:
    """Read-only mapping from review text to user-confirmed sentiment label.

    The CSV is loaded once at construction. Pass an explicit path to control
    where corrections live.
    """

    def __init__(self, csv_path: Path | str | None) -> None:
        self._path = Path(csv_path) if csv_path else None
        self._mapping: dict[str, str] = {}
        if self._path is not None:
            self._load()

    @property
    def size(self) -> int:
        return len(self._mapping)

    @property
    def path(self) -> Path | None:
        return self._path

    def lookup(self, text: str) -> OverrideHit | None:
        """Return an OverrideHit when text exactly matches a known correction."""
        if not text or not self._mapping:
            return None
        label = self._mapping.get(text)
        if label is None:
            return None
        canonical = LEGACY_LABEL_MAP.get(label, label)
        score = _score_for_label(canonical)
        return OverrideHit(
            layer="knowledge_base",
            matched_keywords=[],
            score=score,
            detail=f"KB hit -> {canonical}",
        )

    def _load(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            _logger.info("Knowledge base path does not exist: %s", self._path)
            return
        try:
            df = pd.read_csv(self._path)
        except Exception as exc:
            _logger.warning("Failed to read knowledge base %s: %s", self._path, exc)
            return

        text_col = next((c for c in KB_TEXT_COLUMNS if c in df.columns), None)
        if text_col is None or KB_LABEL_COLUMN not in df.columns:
            _logger.warning(
                "Knowledge base %s missing required columns "
                "(text in %s, label %r)",
                self._path,
                KB_TEXT_COLUMNS,
                KB_LABEL_COLUMN,
            )
            return

        df = df.dropna(subset=[text_col, KB_LABEL_COLUMN])
        self._mapping = dict(
            zip(df[text_col].astype(str), df[KB_LABEL_COLUMN].astype(str), strict=True)
        )
        _logger.info("Loaded %d KB entries from %s", len(self._mapping), self._path)


def _score_for_label(label: str) -> float:
    if label == "POZITIF":
        return KB_POSITIVE_SCORE
    if label == "NEGATIF":
        return KB_NEGATIVE_SCORE
    return KB_NEUTRAL_SCORE
