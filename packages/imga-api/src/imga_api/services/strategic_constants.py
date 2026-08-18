"""Sprint 8.3.6 — strategic-report shared constants.

Industry + company-size enum-to-Türkçe-label maps. Used by the SWOT/OKR
prompt renderer and (Sprint 8.3.6.6) the /settings/profile dropdowns.
The migration 0019 ``tenants.industry`` column stores the enum *code*;
the human label only ever surfaces in prompt text + UI.

The "other" branch is deliberately a sentinel value: when ``industry =
"other"``, ``industry_other_text`` carries the user-typed label and the
prompt renderer prefers it over the generic "Diğer" rendering.
"""

from __future__ import annotations

from typing import Any, Final

INDUSTRY_LABELS: Final[dict[str, str]] = {
    "e_commerce": "E-ticaret",
    "retail": "Perakende",
    "telecom": "Telekomünikasyon",
    "banking": "Bankacılık",
    "insurance": "Sigortacılık",
    "services": "Hizmet sektörü",
    "healthcare": "Sağlık",
    "education": "Eğitim",
    "manufacturing": "Üretim",
    "food_beverage": "Yiyecek-içecek",
    "logistics": "Lojistik-kargo",
    "other": "Diğer",
}

COMPANY_SIZE_LABELS: Final[dict[str, str]] = {
    "solo": "Tek kişi (1)",
    "small": "Küçük (2-10)",
    "medium": "Orta (11-50)",
    "large": "Büyük (51-250)",
    "enterprise": "Kurumsal (251+)",
}


def industry_label(code: str | None, other_text: str | None = None) -> str:
    """Resolve an industry enum code to its Türkçe label.

    Order of precedence:
      1. ``code is None`` → ``"belirsiz"`` (tenant hasn't filled out
         /settings/profile yet — prompt should still render).
      2. ``code == "other"`` AND ``other_text`` is non-empty → return
         the user-typed label verbatim. This is the whole point of
         the sentinel branch.
      3. Known code → mapped label.
      4. Unknown code → return the code itself so an enum drift
         shows up in prompt text instead of silently being mapped to
         ``"Diğer"``.
    """
    if code is None:
        return "belirsiz"
    if code == "other" and other_text:
        return other_text
    return INDUSTRY_LABELS.get(code, code)


def company_size_label(code: str | None) -> str:
    if code is None:
        return "belirsiz"
    return COMPANY_SIZE_LABELS.get(code, code)


def language_directive(language: str | None) -> str:
    """AI çıktı dili yönergesi — system prompt'un SONUNA eklenir (Sprint 12 i18n).

    Kurum dili 'en' ise güçlü bir "yalnız İngilizce" talimatı döndürür; 'tr' veya
    None ise boş (promptlar zaten Türkçe). System prompt'un içeriğini yeniden
    yazmadan, dil-üstü bir katman olarak çalışır — DB-override promptlar dahil."""
    if language == "en":
        return (
            "\n\nIMPORTANT — OUTPUT LANGUAGE: Respond ONLY in English. Every "
            "narrative field, title, summary, analysis, recommendation and label "
            "in your output MUST be written in fluent, professional English, "
            "regardless of the language of the input data or these instructions."
        )
    return ""


def terminology_directive(terminology: list[dict[str, Any]] | None) -> str:
    """Kurum terim sözlüğü yönergesi — system prompt'un SONUNA eklenir
    (2026-08-18, migration 0042 ``tenants.terminology``).

    ``language_directive`` deseniyle birebir aynı: dil-üstü bir katman,
    prompt içeriğini yeniden yazmadan sona eklenir (DB-override
    promptlar dahil). Sözlük boş/None ise boş döner — mevcut kurumlar
    (henüz sözlük doldurmamış) davranışı hiç değişmez.

    ``terminology`` şekli: ``[{"term": str, "note": str}, ...]``
    (``TenantCreateRequest.terminology`` ile aynı — bkz.
    routes/admin/tenants.py). Boş ``term`` girdileri atlanır; ``note``
    opsiyonel.

    JSONB kolonu şemasız — bu fonksiyon dört stratejik servisin
    (SWOT/OKR/brifing/root-cause) ortak yolunda çalışır, o yüzden
    beklenmeyen bir eleman şekli (dict olmayan girdi) burada 500'e
    değil sessiz atlamaya düşmeli."""
    if not terminology:
        return ""
    lines: list[str] = []
    for entry in terminology:
        if not isinstance(entry, dict):
            continue
        term = str(entry.get("term") or "").strip()
        if not term:
            continue
        note = str(entry.get("note") or "").strip()
        lines.append(f"- {term} — {note}" if note else f"- {term}")
    if not lines:
        return ""
    return (
        "\n\nTERİM SÖZLÜĞÜ (bu terimleri AYNEN kullan, eş anlamlısıyla "
        "değiştirme):\n" + "\n".join(lines)
    )
