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
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from imga_core.parsers import detect_nps_column, parse_nps_value
from imga_core.text_utils import normalize_turkish
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from imga_api.services.smart_parser.base import header_matches_any
from imga_api.services.smart_parser.detectors.turkish_date import (
    DATE_HEADER_PATTERNS,
    parse_date_value,
)


class FileParseError(Exception):
    """Generic parse failure (bad encoding, malformed structure)."""


class UnknownColumnError(FileParseError):
    """The requested ``text_column`` (or ``source_column``) was not in
    the header row. Caller surfaces this as a 400 with a Turkish
    message naming the available columns."""


class UnsupportedFormatError(FileParseError):
    """File extension is not .csv / .xlsx (we don't try to sniff bytes —
    spreadsheet authors should rename, not us)."""


# Şablonun opsiyonel tarih kolonu. Tek kaynak services.batch_template
# (TEMPLATE_OPTIONAL_COLUMNS); upload_validation'daki 'yorum' aynası
# gibi burada da literal duruyor.
_TEMPLATE_DATE_COLUMN: str = "tarih"

_DIMENSION_KEYS: tuple[str, ...] = (
    "business_segment",
    "product_line",
    "channel",
    "customer_tier",
)


@dataclass(frozen=True, slots=True)
class ParsedRow:
    """One non-header row from the upload, projected onto the columns
    the user picked. ``row_number`` is 1-indexed against the *data*
    rows (header is 0); the worker uses it for error_summary entries.

    ``nps_score`` is populated when the upload has an auto-detected NPS
    column AND the row's cell parses to a value in [0, 10] (Sprint
    8.3.5). NULL covers both "no column detected" and "column detected
    but this row's value was empty / out of range / non-numeric" — the
    worker increments rows_with_nps only when this is non-null.

    Sprint 9.4 D — ``business_segment`` / ``product_line`` / ``channel``
    / ``customer_tier`` carry the per-tenant business-dimension values
    pulled from the upload. Each is None when (a) the tenant doesn't
    have a CSV column mapping for that dimension or (b) the row's cell
    is empty.

    ``review_date`` is the review's own date from the optional ``tarih``
    column. None when the upload has no date column or the cell didn't
    parse — the row is still analysed; the insert site falls back to the
    ingest moment.
    """

    row_number: int
    text: str
    source: str | None
    nps_score: int | None = None
    business_segment: str | None = None
    product_line: str | None = None
    channel: str | None = None
    customer_tier: str | None = None
    review_date: datetime | None = None


def _normalize_header(name: str) -> str:
    return normalize_turkish(name.strip())


def _load_xlsx(path: Path) -> Workbook:
    """load_workbook sarmalayıcısı. read_only=True satırları diskten
    stream'ler; data_only formülleri cache'lenmiş değerlerine indirger
    (review'lar "=A1+B1" gibi çöp olmasın). Bozuk / yeniden adlandırılmış
    .xlsx'te openpyxl BadZipFile fırlatır — FileParseError'a çevrilmezse
    route catch'lerinden kaçıp 500 üretiyordu (UAT HATA-01)."""
    try:
        return load_workbook(path, read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException) as exc:
        raise FileParseError(
            "Dosya okunamadı — geçerli bir .xlsx dosyası değil ya da bozuk."
        ) from exc


def _resolve_columns(
    header: list[str],
    *,
    text_column: str,
    source_column: str | None,
    dimension_mapping: dict[str, str] | None = None,
) -> tuple[int, int | None, int | None, dict[str, int], int | None]:
    """Return ``(text_idx, source_idx | None, nps_idx | None,
    dimension_idx_by_key, date_idx | None)``. Raises UnknownColumnError
    if text/source column is absent. NPS is auto-detected via the
    imga-core pattern set; missing NPS is fine (returns None) — the
    upload doesn't have to carry an NPS column.

    The date column (``review_date``) is auto-detected the same way:
    şablondaki ``tarih`` kolonu birebir eşleşmeyle önce denenir, sonra
    smart_parser'ın tarih başlık desenleri. Bulunamazsa None — yorumun
    kendi tarihi yok demektir, satır yine analiz edilir.

    Sprint 9.4 D — ``dimension_mapping`` is ``{dimension_key:
    csv_column_name}`` (e.g. ``{"customer_tier": "tier"}``). A
    dimension whose mapped column isn't in the header is silently
    skipped (no UnknownColumnError) — uploads that don't carry every
    configured dimension are common, and refusing them would break
    tenants who add a dimension config before the next CSV cycle.

    Match for text/source/dimensions is case + accent + I/İ-
    insensitive (same fold nps_detector applies to its own pattern
    set, so the two stay in sync as the rules evolve).
    """
    norm_header = [_normalize_header(c) for c in header]
    target_text = _normalize_header(text_column)
    try:
        text_idx = norm_header.index(target_text)
    except ValueError as exc:
        # Sprint 9.8 — OTAN feedback: hata mesajları Türkçe ve
        # eyleme dönük olmalı. İngilizce "text column 'X' not in
        # header" yerine kullanıcıya neyi yapması gerektiğini
        # söyleyen bir mesaj.
        raise UnknownColumnError(
            f"'{text_column}' adlı kolon dosyada bulunamadı. "
            f"Dosyadaki mevcut kolonlar: "
            f"{', '.join(repr(c) for c in header)}. "
            "Lütfen 'Şablonu İndir' butonundan örnek dosyayı alın "
            "ve verinizi 'yorum' kolonuna yapıştırın."
        ) from exc

    source_idx: int | None = None
    if source_column:
        target_source = _normalize_header(source_column)
        try:
            source_idx = norm_header.index(target_source)
        except ValueError as exc:
            raise UnknownColumnError(
                f"'{source_column}' adlı kaynak kolonu dosyada "
                "bulunamadı. Mevcut kolonlar: "
                f"{', '.join(repr(c) for c in header)}."
            ) from exc

    nps_idx: int | None = None
    nps_header = detect_nps_column(header)
    if nps_header is not None:
        nps_idx = header.index(nps_header)

    dimension_idx_by_key: dict[str, int] = {}
    if dimension_mapping:
        for dim_key, csv_column in dimension_mapping.items():
            if dim_key not in _DIMENSION_KEYS:
                # Defensive: unknown dimension keys are ignored rather
                # than raising — the CHECK constraint upstream rejects
                # them at insert, so this is silent dead-code behaviour.
                continue
            target = _normalize_header(csv_column)
            if target in norm_header:
                dimension_idx_by_key[dim_key] = norm_header.index(target)

    skip_idx = {text_idx}
    if source_idx is not None:
        skip_idx.add(source_idx)
    date_idx = _detect_date_column(header, norm_header, skip=skip_idx)

    return text_idx, source_idx, nps_idx, dimension_idx_by_key, date_idx


def _detect_date_column(
    header: list[str],
    norm_header: list[str],
    *,
    skip: set[int],
) -> int | None:
    """Index of the review-date column, or None.

    Şablonun ``tarih`` kolonu birebir eşleşmeyle önceliklidir; dosyada
    hem ``tarih`` hem ``sipariş tarihi`` varsa şablona uyan kazanır.
    ``skip`` kullanıcının açıkça metin/kaynak olarak seçtiği kolonların
    tarih sanılmasını engeller."""
    template_target = _normalize_header(_TEMPLATE_DATE_COLUMN)
    for idx, name in enumerate(norm_header):
        if idx not in skip and name == template_target:
            return idx
    for idx, name in enumerate(header):
        if idx not in skip and header_matches_any(name, DATE_HEADER_PATTERNS):
            return idx
    return None


def _extract_dimensions(
    row: list[Any] | tuple[Any, ...],
    dimension_idx_by_key: dict[str, int],
) -> dict[str, str | None]:
    """Pull dimension cell values out of a row given the resolved
    indices. Empty cells / missing columns map to None; non-empty
    cells are stripped of surrounding whitespace."""
    out: dict[str, str | None] = {key: None for key in _DIMENSION_KEYS}
    for dim_key, idx in dimension_idx_by_key.items():
        if idx >= len(row):
            continue
        raw = row[idx]
        if raw is None:
            continue
        value = str(raw).strip()
        out[dim_key] = value or None
    return out


def _iter_csv(
    path: Path,
    *,
    text_column: str,
    source_column: str | None,
    dimension_mapping: dict[str, str] | None = None,
) -> Iterator[ParsedRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise FileParseError(
                "Dosya boş görünüyor. Lütfen şablonu indirin, "
                "yorumlarınızı doldurun ve yeniden deneyin."
            ) from exc

        (
            text_idx,
            source_idx,
            nps_idx,
            dim_idx_by_key,
            date_idx,
        ) = _resolve_columns(
            header,
            text_column=text_column,
            source_column=source_column,
            dimension_mapping=dimension_mapping,
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
            nps_score: int | None = None
            if nps_idx is not None and nps_idx < len(row):
                nps_score = parse_nps_value(row[nps_idx])
            review_date: datetime | None = None
            if date_idx is not None and date_idx < len(row):
                review_date = parse_date_value(row[date_idx])
            dims = _extract_dimensions(row, dim_idx_by_key)
            yield ParsedRow(
                row_number=i,
                text=text,
                source=source,
                nps_score=nps_score,
                business_segment=dims["business_segment"],
                product_line=dims["product_line"],
                channel=dims["channel"],
                customer_tier=dims["customer_tier"],
                review_date=review_date,
            )


def _iter_xlsx(
    path: Path,
    *,
    text_column: str,
    source_column: str | None,
    dimension_mapping: dict[str, str] | None = None,
) -> Iterator[ParsedRow]:
    workbook = _load_xlsx(path)
    try:
        sheet = workbook.active
        if sheet is None:
            raise FileParseError(
                "Excel dosyasında aktif bir sayfa bulunamadı. "
                "Dosyayı yeniden kaydedin ve tekrar deneyin."
            )

        rows_iter = sheet.iter_rows(values_only=True)
        try:
            raw_header = next(rows_iter)
        except StopIteration as exc:
            raise FileParseError(
                "Dosya boş görünüyor. Lütfen şablonu indirin, "
                "yorumlarınızı doldurun ve yeniden deneyin."
            ) from exc

        header = [str(c) if c is not None else "" for c in raw_header]
        (
            text_idx,
            source_idx,
            nps_idx,
            dim_idx_by_key,
            date_idx,
        ) = _resolve_columns(
            header,
            text_column=text_column,
            source_column=source_column,
            dimension_mapping=dimension_mapping,
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
            nps_score: int | None = None
            if nps_idx is not None and nps_idx < len(row):
                nps_score = parse_nps_value(row[nps_idx])
            # Excel tarih hücreleri openpyxl'den native datetime gelir;
            # parse_date_value bunu metin denemeden önce yakalıyor.
            review_date: datetime | None = None
            if date_idx is not None and date_idx < len(row):
                review_date = parse_date_value(row[date_idx])
            dims = _extract_dimensions(list(row), dim_idx_by_key)
            yield ParsedRow(
                row_number=i,
                text=text,
                source=source,
                nps_score=nps_score,
                business_segment=dims["business_segment"],
                product_line=dims["product_line"],
                channel=dims["channel"],
                customer_tier=dims["customer_tier"],
                review_date=review_date,
            )
    finally:
        workbook.close()


def iter_rows(
    path: Path,
    *,
    text_column: str,
    source_column: str | None = None,
    dimension_mapping: dict[str, str] | None = None,
) -> Iterator[ParsedRow]:
    """Stream rows from a CSV or XLSX upload.

    Caller decides when to chunk (e.g. ``chunked(iter_rows(...), 1000)``).
    Empty / blank rows are silently skipped — the worker counts them in
    ``failed_rows`` only if they have a row but no text.

    Sprint 9.4 D — ``dimension_mapping`` is the per-tenant business
    dimension config (``{dimension_key: csv_column_name}``). Pass the
    fetched mapping in once at job start; the iterator does the per-
    row column lookup. ``None`` (default) preserves the pre-9.4
    behaviour for callers that haven't been migrated.

    ``ParsedRow.review_date`` comes from the auto-detected ``tarih``
    column; None when the upload has no date column or the cell
    doesn't parse.
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _iter_csv(
            path,
            text_column=text_column,
            source_column=source_column,
            dimension_mapping=dimension_mapping,
        )
    if suffix == ".xlsx":
        return _iter_xlsx(
            path,
            text_column=text_column,
            source_column=source_column,
            dimension_mapping=dimension_mapping,
        )
    raise UnsupportedFormatError(
        f"Desteklenmeyen dosya türü: {suffix!r}. "
        "Yalnızca .csv ve .xlsx dosyaları kabul edilir."
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
        workbook = _load_xlsx(path)
        try:
            sheet = workbook.active
            if sheet is None:
                return 0
            max_row: int = int(sheet.max_row or 0)
            return max(0, max_row - 1)
        finally:
            workbook.close()
    raise UnsupportedFormatError(
        f"Desteklenmeyen dosya türü: {suffix!r}. "
        "Yalnızca .csv ve .xlsx dosyaları kabul edilir."
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
        workbook = _load_xlsx(path)
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
        f"Desteklenmeyen dosya türü: {suffix!r}. "
        "Yalnızca .csv ve .xlsx dosyaları kabul edilir."
    )


def peek_detected_nps_column(path: Path) -> str | None:
    """Sprint 8.3.5. Return the header name of the auto-detected NPS
    column, or None if the upload doesn't have one. Thin wrapper around
    ``peek_header()`` + ``detect_nps_column()`` so the worker can record
    ``analyze_batch_jobs.detected_nps_column`` once at job start without
    re-streaming the file. ``iter_rows()`` re-detects internally — the
    two paths are deterministic over the same header so they agree."""
    return detect_nps_column(peek_header(path))


__all__ = [
    "FileParseError",
    "ParsedRow",
    "UnknownColumnError",
    "UnsupportedFormatError",
    "count_rows",
    "iter_rows",
    "peek_detected_nps_column",
    "peek_header",
]
