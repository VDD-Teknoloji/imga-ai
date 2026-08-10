"""ReviewTextDetector — recognise the free-form review/comment column.

2026-08-10. Kullanici raporu: sablonla birebir ayni adli "yorum"
kolonu onizlemede "Yoksay" gorunuyordu — REVIEW_TEXT icin hicbir
dedektor yoktu (orchestrator kimse ateslemeyince None doner, UI bunu
Yoksay onerisine cevirir). Gercek parse yolu kolonu ayrica bulur
(file_parser._resolve_columns), yani analiz dogruydu; hata guven
kiran onizleme etiketiydi.

Sablon kolonu ("yorum") birebir eslesirse guven 1.0 — kullanicinin
gordugu sey sablon sozlesmesinin onaylanmasi olmali. Diger baslik
desenleri + icerik sezgileri (uzun, cok kelimeli, dusuk rakam orani)
kademeli guven verir; basliksiz serbest metin kolonlari da makul bir
oneriyle gelsin diye salt-icerik yolu var.
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

_TEMPLATE_HEADER: Final[str] = "yorum"

_HEADER_PATTERNS: Final[tuple[str, ...]] = (
    "yorum",
    "yorumlar",
    "yorum metni",
    "musteri yorumu",
    "review",
    "reviews",
    "review text",
    "comment",
    "comments",
    "geri bildirim",
    "geribildirim",
    "feedback",
    "sikayet",
    "degerlendirme",
    "mesaj",
    "metin",
)


class ReviewTextDetector(Detector):
    @property
    def field_name(self) -> str:
        return FieldName.REVIEW_TEXT.value

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
        cleaned = [v.strip() for v in sample_values if v and v.strip()]

        if is_template:
            # Sablon sozlesmesi: parse yolu bu kolonu birebir bulur,
            # onizleme de ayni kesinlikle konusmali.
            return DetectorResult(
                field_name=FieldName.REVIEW_TEXT,
                column_name=column_name,
                confidence=1.0,
                sample_values=take_samples(sample_values),
                metadata={"template_header": True},
            )

        if not cleaned:
            if header_hit:
                return DetectorResult(
                    field_name=FieldName.REVIEW_TEXT,
                    column_name=column_name,
                    confidence=0.5,
                    sample_values=[],
                    metadata={"empty_samples": True, "header_hit": True},
                )
            return None

        avg_len = sum(len(v) for v in cleaned) / len(cleaned)
        avg_words = sum(len(v.split()) for v in cleaned) / len(cleaned)
        digit_ratio = sum(
            sum(ch.isdigit() for ch in v) / max(len(v), 1) for v in cleaned
        ) / len(cleaned)

        looks_freeform = avg_len >= 25.0 and avg_words >= 4.0
        mostly_prose = digit_ratio < 0.3

        if not header_hit and not (avg_len >= 40.0 and avg_words >= 6.0):
            return None

        confidence = 0.0
        if header_hit:
            confidence += 0.5
        if looks_freeform:
            confidence += 0.3
        elif not header_hit:
            # Salt-icerik yolunda zaten daha siki esik uygulandi.
            confidence += 0.55
        if mostly_prose:
            confidence += 0.15

        return DetectorResult(
            field_name=FieldName.REVIEW_TEXT,
            column_name=column_name,
            confidence=min(confidence, 1.0),
            sample_values=take_samples(sample_values),
            metadata={
                "avg_length": round(avg_len, 1),
                "avg_words": round(avg_words, 1),
                "digit_ratio": round(digit_ratio, 2),
                "header_hit": header_hit,
            },
        )
