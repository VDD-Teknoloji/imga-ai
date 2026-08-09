"""TurkishDateDetector — date columns including Türkçe month-name forms.

Sprint 8.3.8. Recognises the three formats real Türkçe CSV exports
ship: ``DD/MM/YYYY``, ``DD.MM.YYYY``, and ``DD <Türkçe ay> YYYY``
(``1 Ocak 2026``). 4-digit year is mandatory — ``DD/MM/YY`` is
ambiguous enough that we'd rather miss the column than guess wrong.

``DATE_HEADER_PATTERNS`` + ``parse_date_value`` are public because the
batch parser (``workers.file_parser``) resolves the upload's ``tarih``
kolonunu aynı kurallarla çözüyor — önizlemede "bu kolon tarih" diyip
gerçek parse'ta başka bir liste kullanmak kaçınılmaz olarak
sapardı, o yüzden tek kaynak burası.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Final

from imga_api.services.date_bounds import day_floor
from imga_api.services.smart_parser.base import (
    Detector,
    header_matches_any,
    take_samples,
)
from imga_api.services.smart_parser.types import DetectorResult, FieldName

DATE_HEADER_PATTERNS: Final[tuple[str, ...]] = (
    "tarih",
    "date",
    "created at",
    "created_at",
    "olusturma tarihi",
    "olusturma_tarihi",
    "siparis tarihi",
    "siparis_tarihi",
    "gun",
)

_TR_MONTHS: Final[tuple[str, ...]] = (
    "ocak",
    "subat",
    "mart",
    "nisan",
    "mayis",
    "haziran",
    "temmuz",
    "agustos",
    "eylul",
    "ekim",
    "kasim",
    "aralik",
)

# Three accepted shapes:
#   1) DD/MM/YYYY
#   2) DD.MM.YYYY
#   3) DD <Türkçe ay> YYYY  (case-folded)
_NUMERIC_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{1,2}[\./]\d{1,2}[\./]\d{4}$"
)
_TR_MONTH_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{1,2}\s+(?:" + "|".join(_TR_MONTHS) + r")\s+\d{4}$"
)

# Parse tarafı: gün-ilk sayısal biçimler, isteğe bağlı saat ekiyle.
_DAY_FIRST_FORMATS: Final[tuple[str, ...]] = (
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
)
_TR_MONTH_CAPTURE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(\d{1,2})\s+(" + "|".join(_TR_MONTHS) + r")\s+(\d{4})$"
)
_ASCII_FOLD: Final[tuple[tuple[str, str], ...]] = (
    ("ı", "i"),
    ("ö", "o"),
    ("ü", "u"),
    ("ç", "c"),
    ("ş", "s"),
    ("ğ", "g"),
)


def _fold(value: str) -> str:
    folded = value.lower()
    for tr_ch, ascii_ch in _ASCII_FOLD:
        folded = folded.replace(tr_ch, ascii_ch)
    return folded


def parse_date_value(raw: object) -> datetime | None:
    """Tek bir hücreyi timezone-aware UTC datetime'a çevir; olmuyorsa None.

    Kabul edilenler: openpyxl'in döndürdüğü native ``datetime``/``date``
    hücreleri, ISO (``YYYY-MM-DD`` ve tam timestamp), ``DD.MM.YYYY``,
    ``DD/MM/YYYY`` (ikisi de isteğe bağlı saatle) ve ``DD <Türkçe ay>
    YYYY``. Naive değerler UTC sayılır; saat taşımayan değerler gün
    başına (``day_floor``) sabitlenir ki aynı günün satırları aynı
    bucket'a düşsün.

    None dönmesi hata değildir — çağıran satırı reddetmez, yalnızca
    yorumun kendi tarihi bilinmiyor demektir.
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    if isinstance(raw, date):
        return day_floor(raw)

    text = str(raw).strip()
    if not text:
        return None

    try:
        iso = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        iso = None
    if iso is not None:
        return iso if iso.tzinfo is not None else iso.replace(tzinfo=UTC)

    for fmt in _DAY_FIRST_FORMATS:
        try:
            # DTZ007: biçimlerde %z yok çünkü yüklenen dosyalar saat
            # dilimi taşımıyor; naive sonuç hemen altta UTC'ye bağlanıyor.
            parsed = datetime.strptime(text, fmt)  # noqa: DTZ007
        except ValueError:
            continue
        return parsed.replace(tzinfo=UTC)

    match = _TR_MONTH_CAPTURE_RE.match(_fold(text))
    if match is not None:
        day, month_name, year = match.groups()
        try:
            return day_floor(
                date(int(year), _TR_MONTHS.index(month_name) + 1, int(day))
            )
        except ValueError:
            return None
    return None


class TurkishDateDetector(Detector):
    @property
    def field_name(self) -> str:
        return FieldName.DATE.value

    def detect(
        self,
        column_name: str,
        sample_values: list[str],
        all_columns: list[str],
    ) -> DetectorResult | None:
        del all_columns
        header_hit = header_matches_any(column_name, DATE_HEADER_PATTERNS)
        cleaned = [v.strip() for v in sample_values if v and v.strip()]

        if not cleaned:
            if header_hit:
                return DetectorResult(
                    field_name=FieldName.DATE,
                    column_name=column_name,
                    confidence=0.4,
                    sample_values=[],
                    metadata={"empty_samples": True},
                )
            return None

        match_rate, formats = self._scan(cleaned)
        if not header_hit and match_rate < 0.7:
            return None

        confidence = 0.0
        if header_hit:
            confidence += 0.4
        confidence += 0.6 * match_rate

        return DetectorResult(
            field_name=FieldName.DATE,
            column_name=column_name,
            confidence=min(confidence, 1.0),
            sample_values=take_samples(sample_values),
            metadata={
                "match_rate": round(match_rate, 2),
                "formats": sorted(formats),
                "header_hit": header_hit,
            },
        )

    @staticmethod
    def _scan(values: list[str]) -> tuple[float, set[str]]:
        formats: set[str] = set()
        hits = 0
        for raw in values:
            stripped = raw.strip()
            if _NUMERIC_DATE_RE.match(stripped):
                if "/" in stripped:
                    formats.add("DD/MM/YYYY")
                else:
                    formats.add("DD.MM.YYYY")
                hits += 1
                continue
            # Lowercase + ASCII-fold the month-name path so "Mayıs"
            # / "MAYIS" / "mayis" all match. The regex itself is
            # ASCII-only by design.
            if _TR_MONTH_RE.match(_fold(stripped)):
                formats.add("DD MMM YYYY (TR)")
                hits += 1
        return hits / len(values), formats
