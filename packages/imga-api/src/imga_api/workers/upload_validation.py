"""Sprint 12 — yükleme ön-doğrulaması (pre-flight validation).

Ürün sahibi: "Yanlış formatta yüklerse ona nokta atışı hatayı söyle
ki düzeltsin." Eski akışta yapısal hatalar (kolon yok, dosya boş)
upload anında 400/422 ile yakalanıyordu ama İÇERİK hataları (boş
hücre, kopya satır) yalnızca analiz SIRASINDA sessizce 'failed'
sayılıyordu — kullanıcı uzun işlemin sonunda öğreniyordu.

Bu modül dosyayı analiz başlamadan tarar ve YAPISAL + İÇERİK
sorunlarını satır numarasıyla, düzeltme ipucuyla raporlar. Preview
endpoint bunu Step 2'de gösterir; kullanıcı yüklemeden önce neyi
düzelteceğini görür.

Kapsam (worker semantiğiyle birebir):
  * error (engelleyici):  zorunlu 'yorum' kolonu yok / dosya boş /
                          satır limiti aşıldı.
  * warning (bilgi):      boş 'yorum' hücresi (atlanacak satır) /
                          dosya içi kopya (atlanacak satır) /
                          şablon-görünümlü / anlamsız içerik (2026-08-18,
                          migration 0042 WS2 — satır YİNE analiz edilir,
                          yalnız kullanıcı önceden uyarılır).
  * valid_rows:           analiz edilecek satır = toplam − boş − kopya.
                          informational/meaningless satırlar dahildir —
                          onlar da worker'da analiz edilip quality_flag'li
                          birer Review olarak yazılır, atlanmazlar.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from imga_core.text_utils import normalize_turkish, review_text_hash

from imga_api.services.data_quality import classify_data_quality
from imga_api.workers.file_parser import (
    FileParseError,
    UnknownColumnError,
    UnsupportedFormatError,
    count_rows,
    iter_rows,
    peek_header,
)

# Şablonun zorunlu kolonu. Tek kaynak services.batch_template
# (TEMPLATE_REQUIRED_COLUMNS); workers katmanı services'e bağımlı
# olmasın diye route bunu parametre olarak geçer, default burada
# aynayla durur.
_DEFAULT_REQUIRED_COLUMNS: tuple[str, ...] = ("yorum",)

# Rapor şişmesin: ilk N satır-bazlı sorun listelenir, gerisi sayıya
# katlanır ("ve 124 satır daha"). UI ilk birkaç örneği gösterir;
# kullanıcı deseni anlar.
MAX_REPORTED_ROWS = 50

# Legacy 'text' kolonu hâlâ kabul (geri uyumluluk; _ensure_template_
# compliance ile aynı kapı).
_LEGACY_TEXT_ALIASES = frozenset({"text"})


@dataclass(frozen=True, slots=True)
class UploadValidationIssue:
    """Tek bir doğrulama bulgusu. ``row`` 1-indeksli veri satırı
    (başlık 0); dosya seviyesi bulgularda None."""

    severity: str  # "error" | "warning"
    code: str
    message: str
    row: int | None = None
    column: str | None = None
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class UploadValidationReport:
    ok: bool
    total_rows: int
    valid_rows: int
    error_count: int
    warning_count: int
    issues: list[UploadValidationIssue] = field(default_factory=list)


def _has_required_column(
    header: list[str], required_columns: Sequence[str]
) -> bool:
    normalized = {normalize_turkish(h).strip() for h in header}
    if normalized & _LEGACY_TEXT_ALIASES:
        return True
    return any(normalize_turkish(req) in normalized for req in required_columns)


def _effective_text_column(
    header: list[str], text_column: str, required_columns: Sequence[str]
) -> str:
    """Satır taramasında HANGİ kolonun okunacağını çöz.

    _has_required_column 'text' legacy alias'ını kabul ettiği için,
    şablon kolonu ('yorum') header'da yokken bile dosya uyumlu sayılır.
    Bu durumda tarama 'yorum'u değil gerçekte var olan kolonu okumalı —
    yoksa iter_rows UnknownColumnError atar ve uyumlu dosya yanlışlıkla
    'missing_required_column' olarak işaretlenirdi. Öncelik: istenen
    text_column → şablonun zorunlu kolonu → legacy 'text' alias'ı."""
    normalized = {normalize_turkish(h).strip() for h in header}
    if normalize_turkish(text_column).strip() in normalized:
        return text_column
    for req in required_columns:
        if normalize_turkish(req).strip() in normalized:
            return req
    for alias in _LEGACY_TEXT_ALIASES:
        if alias in normalized:
            return alias
    return text_column


def validate_upload(
    file_path: Path,
    *,
    text_column: str,
    max_rows: int,
    required_columns: Sequence[str] = _DEFAULT_REQUIRED_COLUMNS,
) -> UploadValidationReport:
    """Dosyayı analiz başlamadan tarar ve yapısal + içerik sorunlarını
    raporlar. Engelleyici (error) bir sorun varsa ``ok=False`` döner.

    Çağıran (preview endpoint) dosyayı geçici yola yazdıktan sonra
    bunu çağırır; ``FileParseError`` türevleri burada tek bir
    engelleyici 'error' bulgusuna çevrilir (route 400 üretmez,
    kullanıcıya rapor olarak gösterilir)."""
    issues: list[UploadValidationIssue] = []

    # --- yapısal: başlık + zorunlu kolon -----------------------------
    try:
        header = peek_header(file_path)
    except (FileParseError, UnsupportedFormatError) as exc:
        return UploadValidationReport(
            ok=False,
            total_rows=0,
            valid_rows=0,
            error_count=1,
            warning_count=0,
            issues=[
                UploadValidationIssue(
                    severity="error",
                    code="parse_failed",
                    message=str(exc),
                    hint="Dosyayı şablondan yeniden oluşturup deneyin.",
                )
            ],
        )

    if not _has_required_column(header, required_columns):
        return UploadValidationReport(
            ok=False,
            total_rows=0,
            valid_rows=0,
            error_count=1,
            warning_count=0,
            issues=[
                UploadValidationIssue(
                    severity="error",
                    code="missing_required_column",
                    message=(
                        "Zorunlu 'yorum' kolonu bulunamadı. "
                        f"Dosyadaki kolonlar: {', '.join(repr(h) for h in header)}."
                    ),
                    column="yorum",
                    hint=(
                        "'Şablonu İndir' butonundan Excel şablonunu alın, "
                        "yorumlarınızı 'yorum' kolonuna yapıştırın."
                    ),
                )
            ],
        )

    # --- yapısal: satır sayısı --------------------------------------
    try:
        total_rows = count_rows(file_path)
    except (FileParseError, UnsupportedFormatError) as exc:
        return UploadValidationReport(
            ok=False,
            total_rows=0,
            valid_rows=0,
            error_count=1,
            warning_count=0,
            issues=[
                UploadValidationIssue(
                    severity="error",
                    code="parse_failed",
                    message=str(exc),
                )
            ],
        )

    if total_rows <= 0:
        return UploadValidationReport(
            ok=False,
            total_rows=0,
            valid_rows=0,
            error_count=1,
            warning_count=0,
            issues=[
                UploadValidationIssue(
                    severity="error",
                    code="empty_file",
                    message=(
                        "Dosya boş ya da yalnızca başlık satırı içeriyor."
                    ),
                    hint="Yorumlarınızı 'yorum' kolonuna yazıp tekrar deneyin.",
                )
            ],
        )

    if total_rows > max_rows:
        # Limit aşıldıysa satır taramasına girmeyiz (büyük dosyayı
        # gereksiz okumayalım) — tek engelleyici bulgu yeter.
        return UploadValidationReport(
            ok=False,
            total_rows=total_rows,
            valid_rows=0,
            error_count=1,
            warning_count=0,
            issues=[
                UploadValidationIssue(
                    severity="error",
                    code="too_many_rows",
                    message=(
                        f"Satır sayısı {max_rows:,} sınırını aşıyor "
                        f"(dosyada {total_rows:,} satır var)."
                    ),
                    hint="Dosyayı bölün ve parça parça yükleyin.",
                )
            ],
        )

    # --- içerik: boş hücre + kopya satır taraması --------------------
    # Tarama gerçek metin kolonunu okur (legacy 'text' alias dahil),
    # sabit 'yorum'u değil — bkz. _effective_text_column.
    scan_column = _effective_text_column(header, text_column, required_columns)
    empty_rows: list[int] = []
    duplicate_rows: list[int] = []
    informational_rows: list[int] = []
    meaningless_rows: list[int] = []
    seen_hashes: set[str] = set()
    valid_rows = 0

    try:
        for parsed in iter_rows(file_path, text_column=scan_column):
            text = parsed.text
            if not text:
                empty_rows.append(parsed.row_number)
                continue
            digest = review_text_hash(text)
            if digest in seen_hashes:
                duplicate_rows.append(parsed.row_number)
                continue
            seen_hashes.add(digest)
            valid_rows += 1
            # 2026-08-18 (migration 0042) WS2 — aynı deterministik
            # heuristik worker'ın yazım yolunda kullandığıyla birebir
            # aynı modül (imga_api.services.data_quality). Satır YİNE
            # analiz edilecek (valid_rows'tan düşülmez) — yalnız
            # önceden uyarı olarak gösterilir. Kopya olarak zaten
            # işaretlenmiş satırlara bakılmaz (worker'daki öncelik:
            # dedup > içerik kalitesi).
            quality = classify_data_quality(text)
            if quality == "informational":
                informational_rows.append(parsed.row_number)
            elif quality == "meaningless":
                meaningless_rows.append(parsed.row_number)
    except UnknownColumnError as exc:
        # Şablon uyumlu ama seçilen text_column header'da yoksa.
        return UploadValidationReport(
            ok=False,
            total_rows=total_rows,
            valid_rows=0,
            error_count=1,
            warning_count=0,
            issues=[
                UploadValidationIssue(
                    severity="error",
                    code="missing_required_column",
                    message=str(exc),
                    column=text_column,
                )
            ],
        )
    except (FileParseError, UnsupportedFormatError) as exc:
        return UploadValidationReport(
            ok=False,
            total_rows=total_rows,
            valid_rows=0,
            error_count=1,
            warning_count=0,
            issues=[
                UploadValidationIssue(
                    severity="error", code="parse_failed", message=str(exc)
                )
            ],
        )

    _append_row_warnings(
        issues,
        rows=empty_rows,
        code="empty_text",
        singular="satırda 'yorum' boş — bu satır atlanacak",
        plural="satırda 'yorum' boş — bu satırlar atlanacak",
        column="yorum",
        hint="Boş satırları silin ya da yorum metnini ekleyin.",
    )
    _append_row_warnings(
        issues,
        rows=duplicate_rows,
        code="duplicate",
        singular="satır dosya içinde tekrar ediyor — bir kez analiz edilecek",
        plural="satır dosya içinde tekrar ediyor — her biri bir kez analiz edilecek",
        column=None,
        hint="Aynı yorumu birden çok kez yüklediyseniz tekrarları silebilirsiniz.",
    )
    _append_row_warnings(
        issues,
        rows=informational_rows,
        code="informational",
        singular="satır şablon/otomasyon bildirimi gibi görünüyor "
        "(bilgilendirme, kargo takip vb.) — yine de analiz edilecek",
        plural="satır şablon/otomasyon bildirimi gibi görünüyor "
        "(bilgilendirme, kargo takip vb.) — yine de analiz edilecekler",
        column="yorum",
        hint=(
            "Gerçek müşteri yorumu değilse dosyadan çıkarabilirsiniz; "
            "çıkarmazsanız satır normal şekilde analiz edilir ve "
            "raporlarda düşük kaliteli veri olarak işaretlenir."
        ),
    )
    _append_row_warnings(
        issues,
        rows=meaningless_rows,
        code="meaningless",
        singular="satırın içeriği çok kısa/anlamsız görünüyor "
        "(tek kelime, yalnız rakam vb.) — yine de analiz edilecek",
        plural="satırın içeriği çok kısa/anlamsız görünüyor "
        "(tek kelime, yalnız rakam vb.) — yine de analiz edilecekler",
        column="yorum",
        hint=(
            "Gerçek bir yorum değilse dosyadan çıkarabilirsiniz; "
            "çıkarmazsanız satır normal şekilde analiz edilir ve "
            "raporlarda düşük kaliteli veri olarak işaretlenir."
        ),
    )

    warning_count = (
        len(empty_rows)
        + len(duplicate_rows)
        + len(informational_rows)
        + len(meaningless_rows)
    )
    return UploadValidationReport(
        ok=True,
        total_rows=total_rows,
        valid_rows=valid_rows,
        error_count=0,
        warning_count=warning_count,
        issues=issues,
    )


def _append_row_warnings(
    issues: list[UploadValidationIssue],
    *,
    rows: list[int],
    code: str,
    singular: str,
    plural: str,
    column: str | None,
    hint: str,
) -> None:
    """Satır-bazlı uyarıları rapora ekler. İlk MAX_REPORTED_ROWS satır
    tek tek listelenir; fazlası tek özet bulguya katlanır."""
    if not rows:
        return
    shown = rows[:MAX_REPORTED_ROWS]
    for row_number in shown:
        issues.append(
            UploadValidationIssue(
                severity="warning",
                code=code,
                message=f"{row_number}. {singular}.",
                row=row_number,
                column=column,
                hint=hint,
            )
        )
    remaining = len(rows) - len(shown)
    if remaining > 0:
        issues.append(
            UploadValidationIssue(
                severity="warning",
                code=code,
                message=f"…ve {remaining:,} {plural} daha.",
                column=column,
                hint=hint,
            )
        )


__all__ = [
    "UploadValidationIssue",
    "UploadValidationReport",
    "validate_upload",
]
