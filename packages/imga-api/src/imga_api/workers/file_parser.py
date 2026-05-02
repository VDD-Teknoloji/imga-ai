"""Streaming CSV/XLSX row reader for the batch upload pipeline.

The worker can't load a 50 MB CSV/XLSX into memory all at once — at 10K
rows the dataframe approach would dominate the API container's memory
budget. Both readers iterate row-by-row and yield in caller-controlled
chunks.

Header detection rules (deliberately lenient — uploads come from
spreadsheets that mix Turkish + English column names):

  * The first non-empty row is the header.
  * Header lookup is case-insensitive, trimmed, normalize_turkish'd.
  * If ``text_column`` doesn't match any header → raise UnknownColumnError.

CSV encoding is fixed to UTF-8 with BOM tolerance (``utf-8-sig``);
TR-CP1254 was considered but introduces ambiguity around the Turkish
characters and spreadsheet exports default to UTF-8 today.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from imga_core.text_utils import normalize_turkish
from openpyxl import load_workbook


class FileParseError(Exception):
    """Generic parse failure (bad encoding, malformed structure)."""


class UnknownColumnError(FileParseError):
    """The requested ``text_column`` (or ``source_column``) was not in
    the header row. Caller surfaces this as a 400 with a Turkish
    message naming the available columns."""


class UnsupportedFormatError(FileParseError):
    """File extension is not .csv / .xlsx (we don't try to sniff bytes —
    spreadsheet authors should rename, not us)."""


@dataclass(frozen=True, slots=True)
class ParsedRow:
    """One non-header row from the upload, projected onto the columns
    the user picked. ``row_number`` is 1-indexed against the *data*
    rows (header is 0); the worker uses it for error_summary entries.
    """

    row_number: int
    text: str
    source: str | None


def _normalize_header(name: str) -> str:
    return normalize_turkish(name.strip())


def _resolve_columns(
    header: list[str],
    *,
    text_column: str,
    source_column: str | None,
) -> tuple[int, int | None]:
    """Return (text_idx, source_idx | None). Raises UnknownColumnError
    if either column is absent. Match is case + accent + I/İ-insensitive."""
    norm_header = [_normalize_header(c) for c in header]
    target_text = _normalize_header(text_column)
    try:
        text_idx = norm_header.index(target_text)
    except ValueError as exc:
        raise UnknownColumnError(
            f"text column {text_column!r} not in header (available: "
            f"{', '.join(repr(c) for c in header)})"
        ) from exc

    source_idx: int | None = None
    if source_column:
        target_source = _normalize_header(source_column)
        try:
            source_idx = norm_header.index(target_source)
        except ValueError as exc:
            raise UnknownColumnError(
                f"source column {source_column!r} not in header"
            ) from exc

    return text_idx, source_idx


def _iter_csv(
    path: Path,
    *,
    text_column: str,
    source_column: str | None,
) -> Iterator[ParsedRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise FileParseError("file is empty") from exc

        text_idx, source_idx = _resolve_columns(
            header, text_column=text_column, source_column=source_column
        )
        for i, row in enumerate(reader, start=1):
            if not row:
                continue
            try:
                text = row[text_idx].strip() if text_idx < len(row) else ""
            except IndexError:
                text = ""
            source: str | None = None
            if source_idx is not None and source_idx < len(row):
                raw = row[source_idx].strip()
                source = raw or None
            yield ParsedRow(row_number=i, text=text, source=source)


def _iter_xlsx(
    path: Path,
    *,
    text_column: str,
    source_column: str | None,
) -> Iterator[ParsedRow]:
    # read_only=True streams rows from disk; data_only collapses formulae
    # to their cached values so reviews aren't garbage like "=A1+B1".
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        if sheet is None:
            raise FileParseError("workbook has no active sheet")

        rows_iter = sheet.iter_rows(values_only=True)
        try:
            raw_header = next(rows_iter)
        except StopIteration as exc:
            raise FileParseError("file is empty") from exc

        header = [str(c) if c is not None else "" for c in raw_header]
        text_idx, source_idx = _resolve_columns(
            header, text_column=text_column, source_column=source_column
        )
        for i, row in enumerate(rows_iter, start=1):
            if row is None:
                continue
            text_cell = row[text_idx] if text_idx < len(row) else None
            text = "" if text_cell is None else str(text_cell).strip()
            source: str | None = None
            if source_idx is not None and source_idx < len(row):
                raw_source = row[source_idx]
                if raw_source is not None:
                    source = str(raw_source).strip() or None
            yield ParsedRow(row_number=i, text=text, source=source)
    finally:
        workbook.close()


def iter_rows(
    path: Path,
    *,
    text_column: str,
    source_column: str | None = None,
) -> Iterator[ParsedRow]:
    """Stream rows from a CSV or XLSX upload.

    Caller decides when to chunk (e.g. ``chunked(iter_rows(...), 1000)``).
    Empty / blank rows are silently skipped — the worker counts them in
    ``failed_rows`` only if they have a row but no text.
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _iter_csv(path, text_column=text_column, source_column=source_column)
    if suffix == ".xlsx":
        return _iter_xlsx(path, text_column=text_column, source_column=source_column)
    raise UnsupportedFormatError(
        f"unsupported file extension {suffix!r}; expected .csv or .xlsx"
    )


def count_rows(path: Path) -> int:
    """Cheap row count (header excluded). Used by the upload route to
    populate ``total_rows`` and ``estimated_seconds`` before any
    analysis happens."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return max(0, sum(1 for _ in csv.reader(fh)) - 1)
    if suffix == ".xlsx":
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            if sheet is None:
                return 0
            max_row: int = int(sheet.max_row or 0)
            return max(0, max_row - 1)
        finally:
            workbook.close()
    raise UnsupportedFormatError(
        f"unsupported file extension {suffix!r}; expected .csv or .xlsx"
    )


def peek_header(path: Path) -> list[str]:
    """Return the header row as raw strings (preserving original case
    and Turkish characters). Used by /analyze/batch to surface
    available columns in error responses."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            try:
                return next(csv.reader(fh))
            except StopIteration:
                return []
    if suffix == ".xlsx":
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            if sheet is None:
                return []
            iterator = sheet.iter_rows(values_only=True)
            try:
                row = next(iterator)
            except StopIteration:
                return []
            return [str(c) if c is not None else "" for c in row]
        finally:
            workbook.close()
    raise UnsupportedFormatError(
        f"unsupported file extension {suffix!r}; expected .csv or .xlsx"
    )


__all__ = [
    "FileParseError",
    "ParsedRow",
    "UnknownColumnError",
    "UnsupportedFormatError",
    "count_rows",
    "iter_rows",
    "peek_header",
]
