"""Unit tests for the Sprint 12 pre-flight upload validator.

Pure file IO + parse logic, no DB. Mirrors test_file_parser.py style.
The validator backs the /analyze/batch/preview endpoint's structured
"what's wrong, by row" report.
"""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

from imga_api.workers.upload_validation import validate_upload


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)


def _write_xlsx(path: Path, rows: list[list[str]]) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_clean_file_passes(tmp_path: Path) -> None:
    path = tmp_path / "ok.csv"
    _write_csv(path, [["yorum"], ["ilk yorum"], ["ikinci yorum"]])
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    assert report.ok is True
    assert report.total_rows == 2
    assert report.valid_rows == 2
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.issues == []


def test_missing_required_column_blocks(tmp_path: Path) -> None:
    path = tmp_path / "wrong.csv"
    _write_csv(path, [["comment"], ["a"], ["b"]])
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    assert report.ok is False
    assert report.error_count == 1
    assert report.issues[0].code == "missing_required_column"
    # Pinpoint: names the columns actually present so the user can fix.
    assert "comment" in report.issues[0].message


def test_legacy_text_column_accepted(tmp_path: Path) -> None:
    path = tmp_path / "legacy.csv"
    _write_csv(path, [["text"], ["bir"], ["iki"]])
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    # 'text' is a legacy alias for the required column → not blocked.
    assert report.ok is True
    assert report.valid_rows == 2


def test_empty_file_blocks(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    _write_csv(path, [["yorum"]])  # header only
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    assert report.ok is False
    assert report.issues[0].code == "empty_file"


def test_too_many_rows_blocks(tmp_path: Path) -> None:
    path = tmp_path / "big.csv"
    _write_csv(path, [["yorum"], *[[f"yorum {i}"] for i in range(5)]])
    report = validate_upload(path, text_column="yorum", max_rows=3)
    assert report.ok is False
    assert report.issues[0].code == "too_many_rows"
    assert report.total_rows == 5


def test_empty_text_rows_warn_with_row_numbers(tmp_path: Path) -> None:
    path = tmp_path / "blanks.csv"
    _write_csv(
        path,
        [["yorum"], ["dolu"], [""], ["yine dolu"], ["   "]],
    )
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    assert report.ok is True  # warnings don't block
    assert report.total_rows == 4
    assert report.valid_rows == 2  # the two blank rows are skipped
    codes = [i.code for i in report.issues]
    assert codes.count("empty_text") == 2
    empty_rows = sorted(i.row for i in report.issues if i.code == "empty_text")
    assert empty_rows == [2, 4]  # 1-indexed data rows


def test_duplicate_rows_warn_and_count_once(tmp_path: Path) -> None:
    path = tmp_path / "dupes.csv"
    _write_csv(
        path,
        [["yorum"], ["aynı yorum"], ["AYNI YORUM"], ["farklı"]],
    )
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    assert report.ok is True
    assert report.total_rows == 3
    # casing-only duplicate collapses (review_text_hash normalizes) →
    # only 2 unique rows analyzed.
    assert report.valid_rows == 2
    dup = [i for i in report.issues if i.code == "duplicate"]
    assert len(dup) == 1
    assert dup[0].row == 2


def test_xlsx_clean_file(tmp_path: Path) -> None:
    path = tmp_path / "ok.xlsx"
    _write_xlsx(path, [["yorum"], ["bir"], ["iki"], ["üç"]])
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    assert report.ok is True
    assert report.valid_rows == 3
