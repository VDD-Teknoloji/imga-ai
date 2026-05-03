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

from typing import Final

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
