"""Unit tests for the batch upload file parser.

These run without a DB — pure file IO + parse logic. The integration
tests in test_batch_upload.py exercise the parser end-to-end through
the upload route.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from openpyxl import Workbook

from imga_api.workers.file_parser import (
    FileParseError,
    UnknownColumnError,
    UnsupportedFormatError,
    count_rows,
    iter_rows,
    peek_header,
)


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerows(rows)


def _write_xlsx(path: Path, rows: list[list[str]]) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for row in rows:
        ws.append(row)
    wb.save(path)


# --- count_rows ---------------------------------------------------------


def test_count_rows_csv(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    _write_csv(path, [["text"], ["a"], ["b"], ["c"]])
    assert count_rows(path) == 3


def test_count_rows_xlsx(tmp_path: Path) -> None:
    path = tmp_path / "data.xlsx"
    _write_xlsx(path, [["text"], ["a"], ["b"]])
    assert count_rows(path) == 2


def test_count_rows_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"
    path.write_text("hello")
    with pytest.raises(UnsupportedFormatError):
        count_rows(path)


# --- peek_header --------------------------------------------------------


def test_peek_header_csv(tmp_path: Path) -> None:
    path = tmp_path / "h.csv"
    _write_csv(path, [["yorum", "kaynak"], ["x", "y"]])
    assert peek_header(path) == ["yorum", "kaynak"]


def test_peek_header_xlsx_with_blanks(tmp_path: Path) -> None:
    path = tmp_path / "h.xlsx"
    _write_xlsx(path, [["text", ""], ["x", "y"]])
    assert peek_header(path) == ["text", ""]


# --- iter_rows ----------------------------------------------------------


def test_iter_rows_csv_text_only(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    _write_csv(path, [["yorum"], ["birinci"], ["ikinci"], ["üçüncü"]])
    rows = list(iter_rows(path, text_column="yorum"))
    assert [r.text for r in rows] == ["birinci", "ikinci", "üçüncü"]
    assert [r.row_number for r in rows] == [1, 2, 3]
    assert all(r.source is None for r in rows)


def test_iter_rows_with_source_column(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    _write_csv(
        path,
        [
            ["text", "source"],
            ["yorum a", "trustpilot"],
            ["yorum b", ""],
        ],
    )
    rows = list(
        iter_rows(path, text_column="text", source_column="source")
    )
    assert rows[0].source == "trustpilot"
    assert rows[1].source is None  # empty cell collapses to None


def test_iter_rows_turkish_case_insensitive_header(tmp_path: Path) -> None:
    """User wrote 'Yorum' but the column matches case-insensitively."""
    path = tmp_path / "rows.csv"
    _write_csv(path, [["Yorum"], ["test"]])
    rows = list(iter_rows(path, text_column="yorum"))
    assert len(rows) == 1
    assert rows[0].text == "test"


def test_iter_rows_unknown_column_raises(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    _write_csv(path, [["text"], ["x"]])
    with pytest.raises(UnknownColumnError) as ei:
        list(iter_rows(path, text_column="yorum"))
    assert "yorum" in str(ei.value)


def test_iter_rows_xlsx_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "rows.xlsx"
    _write_xlsx(
        path,
        [
            ["yorum", "kaynak"],
            ["bir yorum", "trustpilot"],
            ["başka bir yorum", ""],
        ],
    )
    rows = list(
        iter_rows(path, text_column="yorum", source_column="kaynak")
    )
    assert [r.text for r in rows] == ["bir yorum", "başka bir yorum"]
    assert [r.source for r in rows] == ["trustpilot", None]


def test_iter_rows_csv_skips_completely_empty_rows(tmp_path: Path) -> None:
    """A blank line in the CSV body shouldn't break enumeration."""
    path = tmp_path / "rows.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("text\n")
        fh.write("ilk\n")
        fh.write("\n")  # totally blank line
        fh.write("son\n")
    rows = list(iter_rows(path, text_column="text"))
    assert [r.text for r in rows] == ["ilk", "son"]


def test_iter_rows_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("")
    with pytest.raises(FileParseError):
        list(iter_rows(path, text_column="text"))
