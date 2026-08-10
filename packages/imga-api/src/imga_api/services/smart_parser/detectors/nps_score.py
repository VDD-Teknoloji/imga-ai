"""NpsScoreDetector — recognise the 0-10 NPS column.

2026-08-10, ReviewTextDetector ile ayni duzeltme dalgasi: FieldName
enum'unda NPS_SCORE vardi ama dedektoru yoktu; sablonun "nps" kolonu
onizlemede "Yoksay" gorunuyordu. Gercek parse yolu NPS'i imga-core
desen setiyle ayrica bulur (detect_nps_column); burasi yalnizca
onizlemenin ayni dili konusmasi icin.
"""

from __future__ import annotations

from typing import Final

from imga_api.services.smart_parser.base import (
    Detector,
    header_matches_any,
    normalize_header,
    take_samples,
)
from imga_api.services.smart_parser.types import DetectorResult, FieldName

_TEMPLATE_HEADER: Final[str] = "nps"

_HEADER_PATTERNS: Final[tuple[str, ...]] = (
    "nps",
    "nps skoru",
    "nps score",
    "nps puani",
    "tavsiye puani",
    "tavsiye skoru",
)


def _int_in_nps_range(value: str) -> bool:
    s = value.strip()
    if not s:
        return False
    try:
        n = int(float(s.replace(",", ".")))
    except ValueError:
        return False
    return 0 <= n <= 10


class NpsScoreDetector(Detector):
    @property
    def field_name(self) -> str:
        return FieldName.NPS_SCORE.value

    def detect(
        self,
        column_name: str,
        sample_values: list[str],
        all_columns: list[str],
    ) -> DetectorResult | None:
        del all_columns
        is_template = normalize_header(column_name) == _TEMPLATE_HEADER
        header_hit = is_template or header_matches_any(
            column_name, _HEADER_PATTERNS
        )
        if not header_hit:
            # Salt-icerik NPS tahmini (0-10 tamsayi kolonlari) kasitli
            # olarak yok: adet/puan/miktar kolonlariyla karisir.
            return None

        cleaned = [v for v in sample_values if v and v.strip()]
        in_range = (
            sum(_int_in_nps_range(v) for v in cleaned) / len(cleaned)
            if cleaned
            else 0.0
        )

        confidence = 0.95 if is_template else 0.6
        if cleaned and in_range >= 0.9:
            confidence = min(confidence + 0.05, 1.0)
        elif cleaned and in_range < 0.5:
            # Baslik NPS diyor ama degerler 0-10 degil — yine oner,
            # dusuk guvenle (kullanici acilir listeden duzeltir).
            confidence = 0.35

        return DetectorResult(
            field_name=FieldName.NPS_SCORE,
            column_name=column_name,
            confidence=confidence,
            sample_values=take_samples(sample_values),
            metadata={
                "template_header": is_template,
                "in_range_ratio": round(in_range, 2),
            },
        )
