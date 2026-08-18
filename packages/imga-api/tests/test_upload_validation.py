"""Unit tests for the Sprint 12 pre-flight upload validator.

Pure file IO + parse logic, no DB. Mirrors test_file_parser.py style.
The validator backs the /analyze/batch/preview endpoint's structured
"what's wrong, by row" report.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from openpyxl import Workbook

from imga_api.services.smart_parser.sampler import sample_columns
from imga_api.workers.file_parser import (
    FileParseError,
    count_rows,
    peek_header,
)
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
    # 2026-08-18 (migration 0042 WS2) — placeholder text needs to be
    # long/substantive enough to dodge the new informational/
    # meaningless heuristic (classify_data_quality); a bare 2-word
    # "ilk yorum" would legitimately trip the <=2-meaningful-word
    # 'meaningless' rule and this test is specifically about a file
    # with ZERO warnings.
    path = tmp_path / "ok.csv"
    _write_csv(
        path,
        [
            ["yorum"],
            ["Ürün tam zamanında elime ulaştı"],
            ["Paketleme oldukça özenliydi bence"],
        ],
    )
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


def test_informational_rows_warn_but_still_count_as_valid(
    tmp_path: Path,
) -> None:
    """2026-08-18 (migration 0042 WS2). Unlike empty/duplicate, an
    informational-looking row is NOT excluded from valid_rows — the
    worker still analyzes and persists it, just with quality_flag set.
    The preview only warns."""
    path = tmp_path / "info.csv"
    _write_csv(
        path,
        [
            ["yorum"],
            ["Değerli müşterimiz, siparişiniz kargoya verildi."],
            ["Ürün tam zamanında elime ulaştı, çok memnun kaldım."],
        ],
    )
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    assert report.ok is True
    assert report.total_rows == 2
    assert report.valid_rows == 2  # NOT subtracted, unlike empty/duplicate
    info = [i for i in report.issues if i.code == "informational"]
    assert len(info) == 1
    assert info[0].row == 1
    assert info[0].severity == "warning"


def test_meaningless_rows_warn_but_still_count_as_valid(
    tmp_path: Path,
) -> None:
    path = tmp_path / "meaningless.csv"
    _write_csv(
        path,
        [
            ["yorum"],
            ["Tamam"],
            ["Ürün gerçekten kaliteliydi, tekrar alırım kesinlikle."],
        ],
    )
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    assert report.ok is True
    assert report.valid_rows == 2
    meaningless = [i for i in report.issues if i.code == "meaningless"]
    assert len(meaningless) == 1
    assert meaningless[0].row == 1


def test_duplicate_row_is_not_also_flagged_meaningless(
    tmp_path: Path,
) -> None:
    """Priority mirrors the worker's write path: a row already
    marked 'duplicate' never gets a second content-quality pass —
    dedup wins."""
    path = tmp_path / "dup_short.csv"
    _write_csv(path, [["yorum"], ["ok"], ["ok"]])
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    codes_for_row_2 = [i.code for i in report.issues if i.row == 2]
    assert codes_for_row_2 == ["duplicate"]


def test_xlsx_clean_file(tmp_path: Path) -> None:
    path = tmp_path / "ok.xlsx"
    _write_xlsx(path, [["yorum"], ["bir"], ["iki"], ["üç"]])
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    assert report.ok is True
    assert report.valid_rows == 3


def _write_corrupt_xlsx(path: Path) -> Path:
    # zip imzası olmayan rastgele baytlar — .xlsx uzantılı ama Excel'de
    # açılmayan / yeniden adlandırılmış dosyayı taklit eder (UAT HATA-01).
    path.write_bytes(b"\x89bozuk dosya \x00\xff\xfe bu bir zip degil")
    return path


def test_corrupt_xlsx_reports_parse_failed(tmp_path: Path) -> None:
    path = _write_corrupt_xlsx(tmp_path / "bozuk.xlsx")
    report = validate_upload(path, text_column="yorum", max_rows=10_000)
    assert report.ok is False
    assert report.error_count == 1
    issue = report.issues[0]
    assert issue.severity == "error"
    assert issue.code == "parse_failed"
    assert "geçerli bir .xlsx" in issue.message


def test_corrupt_xlsx_raises_file_parse_error_for_upload_flow(
    tmp_path: Path,
) -> None:
    # create_batch yalnız FileParseError yakalar; BadZipFile buna
    # çevrilmezse upload 400 yerine 500 üretiyordu (UAT HATA-01).
    path = _write_corrupt_xlsx(tmp_path / "bozuk.xlsx")
    with pytest.raises(FileParseError):
        peek_header(path)
    with pytest.raises(FileParseError):
        count_rows(path)


def test_corrupt_xlsx_raises_file_parse_error_for_preview_sampler(
    tmp_path: Path,
) -> None:
    path = _write_corrupt_xlsx(tmp_path / "bozuk.xlsx")
    with pytest.raises(FileParseError):
        sample_columns(path)
