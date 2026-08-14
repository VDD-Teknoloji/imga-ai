"""SWOT / OKR payload normalization — tek choke-point.

OpenRouter yolu JSON şemayı ``strict: false`` ile yalnız tavsiye olarak
gönderiyor (GLM vb. modeller madde-içi zorunlu alanları atlayabiliyor);
Gemini SDK yolunda da şema zorlaması bir SDK regresyonuyla düşebilir.
Tüketiciler ise tam şekil varsayar: okr_v1 prompt'u ve templates/pdf/
şablonları StrictUndefined Jinja ile ``s.evidence`` / ``r.priority``
gibi alanları koşulsuz basar, frontend ``rec.priority.toLowerCase()``
çağırır. Eksik alanlı bir payload JSONB'ye sızarsa her okuma kalıcı
500'e dönüşür.

Bu modül iki yerde çalışır:

  * **Yazım yolu** — SwotService / OkrService validasyonu persist
    öncesi payload'ı tam şekle getirir (yeni satırlar hep temiz).
  * **Okuma yolu** — pdf_render + OkrService._render_context eski /
    ileride sızabilecek satırlara karşı aynı fonksiyonlardan geçer.

Normalizasyon kuralları: liste-olmayan bölüm → [], dict-olmayan madde
→ atla, eksik/yanlış-tipli metin alanı → "", eksik/yanlış-tipli
priority / estimated_impact → "orta" (frontend SWOT_PRIORITY_TONE
yüksek/orta/düşük stillendiriyor; nötr orta seçildi). Tam şekilli bir
payload değer olarak aynen korunur; bilinmeyen ekstra anahtarlara
dokunulmaz.
"""

from __future__ import annotations

from typing import Any

_SWOT_SECTIONS = ("strengths", "weaknesses", "opportunities", "threats")
_SWOT_ITEM_TEXT_FIELDS = ("title", "description", "evidence")
_RECOMMENDATION_TEXT_FIELDS = ("title", "description")
_RECOMMENDATION_ENUM_FIELDS = ("priority", "estimated_impact")
_KEY_RESULT_TEXT_FIELDS = ("text", "metric", "baseline", "target")
_DEFAULT_PRIORITY = "orta"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    return value if isinstance(value, str) else ""


def _normalize_items(
    value: Any, text_fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        norm = dict(item)
        for key in text_fields:
            norm[key] = _text(item, key)
        out.append(norm)
    return out


def normalize_swot_payload(payload: Any) -> dict[str, Any]:
    """Return a full-shaped copy of a SWOT ``output_payload``.

    Guarantees: all four section keys + strategic_recommendations are
    lists of dicts; every item carries title/description/evidence as
    strings; every recommendation additionally carries priority +
    estimated_impact strings.
    """
    if not isinstance(payload, dict):
        payload = {}
    out = dict(payload)
    for section in _SWOT_SECTIONS:
        out[section] = _normalize_items(
            payload.get(section), _SWOT_ITEM_TEXT_FIELDS
        )
    recs = _normalize_items(
        payload.get("strategic_recommendations"), _RECOMMENDATION_TEXT_FIELDS
    )
    for rec in recs:
        for key in _RECOMMENDATION_ENUM_FIELDS:
            if not isinstance(rec.get(key), str):
                rec[key] = _DEFAULT_PRIORITY
    out["strategic_recommendations"] = recs
    return out


def normalize_okr_payload(payload: Any) -> dict[str, Any]:
    """Return a full-shaped copy of an OKR ``output_payload``.

    Guarantees: ``objectives`` is a list of dicts; every objective
    carries objective/rationale strings + a key_results list; every
    key result carries text/metric/baseline/target strings.
    """
    if not isinstance(payload, dict):
        payload = {}
    out = dict(payload)
    objectives: list[dict[str, Any]] = []
    for obj in _as_list(payload.get("objectives")):
        if not isinstance(obj, dict):
            continue
        norm = dict(obj)
        norm["objective"] = _text(obj, "objective")
        norm["rationale"] = _text(obj, "rationale")
        norm["key_results"] = _normalize_items(
            obj.get("key_results"), _KEY_RESULT_TEXT_FIELDS
        )
        objectives.append(norm)
    out["objectives"] = objectives
    return out


__all__ = [
    "normalize_okr_payload",
    "normalize_swot_payload",
]
