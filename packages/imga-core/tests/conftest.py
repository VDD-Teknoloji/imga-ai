"""Shared pytest fixtures for imga-core tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_kb_csv(tmp_path: Path) -> Iterator[Path]:
    """Create a temporary knowledge-base CSV file."""
    csv = tmp_path / "training_data.csv"
    csv.write_text(
        "Müşteri Yorumu,Correct Label\n"
        "Bu ürün harikaydı çok memnunum,Pozitif\n"
        "Hiç beğenmedim berbat,Negatif\n",
        encoding="utf-8",
    )
    yield csv
