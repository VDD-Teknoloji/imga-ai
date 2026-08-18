"""Sprint 9.4 D — file parser dimension extraction tests.

Pre-9.4 the batch upload pipeline ignored business-dimension
columns entirely — a CSV with a ``tier`` column landed reviews
with ``customer_tier=NULL`` even when the tenant had configured
the mapping. The parser now accepts a ``dimension_mapping`` and
emits the four optional ``ParsedRow`` fields (business_segment,
product_line, channel, customer_tier).

These tests pin the per-row extraction behaviour: present-in-
header keys map, missing-from-header keys silently None (we do
not fail the upload — tenants legitimately mid-migrate dimension
configs), empty cells become None.

2026-08-18 (migration 0042) — ``entered_by`` joined as the 5th
dimension key (the employee who logged the review); it flows
through the exact same generic ``_DIMENSION_KEYS`` / mapping
mechanism as the original four, so it's covered here rather than
in a separate module.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from imga_api.workers.file_parser import (
    UnknownColumnError,
    iter_rows,
)


def _write_csv(tmp_path: Path, *, name: str, rows: list[list[str]]) -> Path:
    path = tmp_path / name
    with path.open("w", encoding="utf-8", newline="") as fh:
        for row in rows:
            fh.write(",".join(row) + "\n")
    return path


def test_parser_emits_dimensions_when_mapping_matches_header(
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(
        tmp_path,
        name="upload.csv",
        rows=[
            ["text", "tier", "channel"],
            ["kargo geç geldi", "premium", "web"],
            ["paket harika", "basic", "mobile"],
        ],
    )
    rows = list(
        iter_rows(
            csv_path,
            text_column="text",
            dimension_mapping={
                "customer_tier": "tier",
                "channel": "channel",
            },
        )
    )

    assert len(rows) == 2
    assert rows[0].text == "kargo geç geldi"
    assert rows[0].customer_tier == "premium"
    assert rows[0].channel == "web"
    # business_segment / product_line not mapped → None.
    assert rows[0].business_segment is None
    assert rows[0].product_line is None

    assert rows[1].customer_tier == "basic"
    assert rows[1].channel == "mobile"


def test_parser_skips_unmapped_dimensions_gracefully(
    tmp_path: Path,
) -> None:
    """Tenant has ``customer_tier`` configured but the CSV they just
    uploaded doesn't include that column. The upload must succeed —
    the dimension cell just lands NULL on the Review row."""
    csv_path = _write_csv(
        tmp_path,
        name="upload.csv",
        rows=[
            ["text", "kanal"],  # no "tier" column
            ["yine geç", "telefon"],
        ],
    )
    # Mapping references a non-existent column; expected: silent skip.
    rows = list(
        iter_rows(
            csv_path,
            text_column="text",
            dimension_mapping={"customer_tier": "tier"},
        )
    )

    assert len(rows) == 1
    assert rows[0].customer_tier is None


def test_parser_empty_dimension_cell_becomes_none(
    tmp_path: Path,
) -> None:
    """An empty / whitespace cell is treated identically to a missing
    column — we do not store the empty string, so the dashboard's
    'tüm değerler' bucket isn't polluted with an empty label."""
    csv_path = _write_csv(
        tmp_path,
        name="upload.csv",
        rows=[
            ["text", "tier"],
            ["row a", "premium"],
            ["row b", "   "],  # whitespace
            ["row c", ""],     # empty
        ],
    )
    rows = list(
        iter_rows(
            csv_path,
            text_column="text",
            dimension_mapping={"customer_tier": "tier"},
        )
    )

    assert rows[0].customer_tier == "premium"
    assert rows[1].customer_tier is None
    assert rows[2].customer_tier is None


def test_parser_emits_entered_by_when_mapping_matches_header(
    tmp_path: Path,
) -> None:
    """2026-08-18 (migration 0042) — 5th dimension: entered_by."""
    csv_path = _write_csv(
        tmp_path,
        name="upload.csv",
        rows=[
            ["text", "calisan"],
            ["kargo geç geldi", "Ahmet Yılmaz"],
            ["paket harika", ""],
        ],
    )
    rows = list(
        iter_rows(
            csv_path,
            text_column="text",
            dimension_mapping={"entered_by": "calisan"},
        )
    )
    assert rows[0].entered_by == "Ahmet Yılmaz"
    assert rows[1].entered_by is None  # empty cell → None, same as the others


def test_parser_unknown_dimension_key_silently_dropped(
    tmp_path: Path,
) -> None:
    """A mapping entry pointing at a dimension key that isn't one of
    the five canonical keys (business_segment / product_line /
    channel / customer_tier / entered_by) is dropped — the CHECK
    constraint on ``tenant_business_dimensions.dimension`` already
    rejects unknown keys at insert, but the parser should not blow up
    on them either."""
    csv_path = _write_csv(
        tmp_path,
        name="upload.csv",
        rows=[
            ["text", "tier", "future_dim"],
            ["row a", "premium", "X"],
        ],
    )
    rows = list(
        iter_rows(
            csv_path,
            text_column="text",
            dimension_mapping={
                "customer_tier": "tier",
                "future_unknown_dim": "future_dim",
            },
        )
    )
    assert rows[0].customer_tier == "premium"
    # Unknown key didn't crash + didn't get persisted.
    assert not hasattr(rows[0], "future_unknown_dim")


def test_parser_no_mapping_keeps_dimensions_none(
    tmp_path: Path,
) -> None:
    """Default-None preserves the pre-9.4 contract: callers that
    haven't been migrated still get ParsedRow with None dimensions."""
    csv_path = _write_csv(
        tmp_path,
        name="upload.csv",
        rows=[
            ["text"],
            ["row a"],
        ],
    )
    rows = list(iter_rows(csv_path, text_column="text"))
    assert rows[0].business_segment is None
    assert rows[0].product_line is None
    assert rows[0].channel is None
    assert rows[0].customer_tier is None
    assert rows[0].entered_by is None


def test_parser_text_column_missing_still_raises(
    tmp_path: Path,
) -> None:
    """Sanity: dimension support didn't accidentally relax the text-
    column-required contract."""
    csv_path = _write_csv(
        tmp_path,
        name="upload.csv",
        rows=[["yorum"], ["foo"]],  # header is "yorum", we ask for "text"
    )
    with pytest.raises(UnknownColumnError):
        list(iter_rows(csv_path, text_column="text"))
