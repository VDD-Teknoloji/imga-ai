"""Unit tests for the batch upload file parser.

These run without a DB — pure file IO + parse logic. The integration
tests in test_batch_upload.py exercise the parser end-to-end through
the upload route.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def _write_xlsx(path: Path, rows: list[list[Any]]) -> None:
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


# --- review_date (yorumun kendi tarihi) ---------------------------------


def test_iter_rows_without_date_column_yields_none(tmp_path: Path) -> None:
    path = tmp_path / "nodate.csv"
    _write_csv(path, [["yorum"], ["tarihsiz yorum"]])
    rows = list(iter_rows(path, text_column="yorum"))
    assert rows[0].review_date is None


@pytest.mark.parametrize(
    "cell, expected",
    [
        ("2026-05-12", datetime(2026, 5, 12, tzinfo=UTC)),
        ("12.05.2026", datetime(2026, 5, 12, tzinfo=UTC)),
        ("12/05/2026", datetime(2026, 5, 12, tzinfo=UTC)),
        ("12 Mayıs 2026", datetime(2026, 5, 12, tzinfo=UTC)),
        ("1 Ocak 2026", datetime(2026, 1, 1, tzinfo=UTC)),
        ("2026-05-12T10:30:00Z", datetime(2026, 5, 12, 10, 30, tzinfo=UTC)),
        ("12.05.2026 14:35", datetime(2026, 5, 12, 14, 35, tzinfo=UTC)),
    ],
)
def test_iter_rows_parses_supported_date_formats(
    tmp_path: Path, cell: str, expected: datetime
) -> None:
    path = tmp_path / "dates.csv"
    _write_csv(path, [["yorum", "tarih"], ["bir yorum", cell]])
    rows = list(iter_rows(path, text_column="yorum"))
    assert rows[0].review_date == expected


@pytest.mark.parametrize("cell", ["", "  ", "yakında", "12/2026", "45000"])
def test_iter_rows_unparseable_date_keeps_row(tmp_path: Path, cell: str) -> None:
    """Bozuk tarih satırı düşürmez — yorum analiz edilmeye devam eder."""
    path = tmp_path / "baddate.csv"
    _write_csv(path, [["yorum", "tarih"], ["bir yorum", cell]])
    rows = list(iter_rows(path, text_column="yorum"))
    assert len(rows) == 1
    assert rows[0].text == "bir yorum"
    assert rows[0].review_date is None


def test_iter_rows_detects_non_template_date_header(tmp_path: Path) -> None:
    """Şablon dışı ama tanınan başlık: 'Sipariş Tarihi'."""
    path = tmp_path / "siparis.csv"
    _write_csv(
        path,
        [["yorum", "Sipariş Tarihi"], ["bir yorum", "03.03.2026"]],
    )
    rows = list(iter_rows(path, text_column="yorum"))
    assert rows[0].review_date == datetime(2026, 3, 3, tzinfo=UTC)


def test_iter_rows_prefers_template_tarih_over_other_date_column(
    tmp_path: Path,
) -> None:
    path = tmp_path / "iki-tarih.csv"
    _write_csv(
        path,
        [
            ["yorum", "siparis tarihi", "tarih"],
            ["bir yorum", "01.01.2026", "02.02.2026"],
        ],
    )
    rows = list(iter_rows(path, text_column="yorum"))
    assert rows[0].review_date == datetime(2026, 2, 2, tzinfo=UTC)


def test_iter_rows_xlsx_native_datetime_cell(tmp_path: Path) -> None:
    """Excel tarih hücresi openpyxl'den datetime gelir (string değil)."""
    path = tmp_path / "dates.xlsx"
    # DTZ001: openpyxl naive datetime döndürür — gerçek hücre davranışı
    # bu, parser'ın UTC'ye bağlaması sınanıyor.
    naive_cell = datetime(2026, 5, 12, 9, 15)  # noqa: DTZ001
    _write_xlsx(path, [["yorum", "tarih"], ["bir yorum", naive_cell]])
    rows = list(iter_rows(path, text_column="yorum"))
    assert rows[0].review_date == datetime(2026, 5, 12, 9, 15, tzinfo=UTC)


def test_iter_rows_text_column_named_tarih_is_not_taken_as_date(
    tmp_path: Path,
) -> None:
    """Metin kolonu 'tarih' seçilirse tarih kolonu olarak sayılmaz."""
    path = tmp_path / "clash.csv"
    _write_csv(path, [["tarih"], ["bu bir yorum"]])
    rows = list(iter_rows(path, text_column="tarih"))
    assert rows[0].text == "bu bir yorum"
    assert rows[0].review_date is None


def test_iter_rows_source_column_named_tarih_is_not_taken_as_date(
    tmp_path: Path,
) -> None:
    path = tmp_path / "src-clash.csv"
    _write_csv(path, [["yorum", "tarih"], ["bir yorum", "02.02.2026"]])
    rows = list(iter_rows(path, text_column="yorum", source_column="tarih"))
    assert rows[0].source == "02.02.2026"
    assert rows[0].review_date is None
