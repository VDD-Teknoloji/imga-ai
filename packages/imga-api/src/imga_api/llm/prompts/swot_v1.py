"""SWOT v1 prompt + response schema.

Sprint 8.3.6 / Alt-Faz 8.3.6.3.B. Module-resident (not DB-resident).
Migration 0019 seeds a ``prompt_templates.template_key='swot_v1'`` row
with placeholder content + ``is_active=false`` so the registry table
exists for future tenant-override work; the actual system /
user-template / schema served to Gemini today comes from THIS file.

The user-prompt template uses Jinja2 because the rendering has
conditionals (industry_other_text, NPS-empty branch) and loops (top
categories, top perspectives) that f-strings would make ugly.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any

from jinja2 import Environment, StrictUndefined

# ---------------------------------------------------------------------------
# Response schema (structured output)
# ---------------------------------------------------------------------------
#
# Master prompt's spec, with one Gemini-imposed limitation: the SDK's
# proto-based Schema type does not understand JSON Schema's
# ``minItems`` / ``maxItems`` keywords (8.3.6.6 round-1 production
# crash: ``ValueError: Unknown field for Schema: minItems``). The
# count constraints (2-6 per SWOT category, 3-5 recommendations) live
# in the system prompt instead, with a permissive service-side guard
# that logs (but does NOT reject) out-of-range counts so a model
# misbehavior never blackouts the dashboard.

SWOT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "strengths",
        "weaknesses",
        "opportunities",
        "threats",
        "strategic_recommendations",
    ],
    "properties": {
        "strengths": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "description", "evidence"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
        "weaknesses": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "description", "evidence"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
        "opportunities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "description", "evidence"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
        "threats": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "description", "evidence"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
        "strategic_recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "title",
                    "description",
                    "priority",
                    "estimated_impact",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    # Sprint 8.3.6.6 round-3 — Gemini SDK rejects ``enum``
                    # without an explicit ``type: "string"``. The 400
                    # response was: "enum: only allowed for STRING
                    # type". JSON Schema treats ``type`` as optional
                    # alongside ``enum``; the SDK does not.
                    "priority": {
                        "type": "string",
                        "enum": ["yüksek", "orta", "düşük"],
                    },
                    "estimated_impact": {
                        "type": "string",
                        "enum": ["yüksek", "orta", "düşük"],
                    },
                },
            },
        },
    },
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SWOT_SYSTEM_PROMPT = """\
Sen kıdemli bir müşteri deneyimi (CX) ve iş stratejisi danışmanısın. \
Türkiye'de faaliyet gösteren şirketlere veri-odaklı, eyleme dönüştürülebilir \
SWOT analizleri sunuyorsun.

GÖREV:
Sana sunulan istatistikler ve şirket bağlamı ışığında bir SWOT analizi \
oluştur. Her madde için:
- title: kısa ve net başlık (5-10 kelime)
- description: 2-3 cümlelik açıklama
- evidence: hangi sayı/metrik bu yargıyı destekliyor (zorunlu)

Stratejik öneriler bölümünde 3-5 somut aksiyon öner. Her öneri için:
- title: aksiyonun adı
- description: nasıl uygulanacağı (2-3 cümle)
- priority: yüksek/orta/düşük
- estimated_impact: yüksek/orta/düşük

KURALLAR:
1. Sayı/metrik uydurma. Sadece sana verilen istatistikleri kullan.
2. "evidence" alanını HİÇBİR zaman boş bırakma. Hangi sayı bu yargıyı \
   destekliyorsa belirt. Sayı yoksa o yargıyı verme.
3. Türkçe yaz. Profesyonel ama anlaşılır dil kullan.
4. Sektör ve şirket büyüklüğüne uygun ölçek ve ton kullan.
5. SWOT maddeleri çeşitli olsun — aynı konuyu hem zayıflık hem tehdit \
   olarak yazma.
6. Stratejik öneriler SMART olsun (specific, measurable, achievable, \
   relevant, time-bound).
7. JSON formatında, response_schema'ya tam uyumlu yanıt ver.
8. Her SWOT kategorisinde (Güçlü Yönler, Zayıf Yönler, Fırsatlar, \
   Tehditler) en az 2, en fazla 6 madde olsun. Stratejik öneriler \
   bölümünde 3-5 öneri olsun.
9. priority alanı SADECE "yüksek", "orta" veya "düşük" değerlerinden \
   biri olmalı. estimated_impact alanı SADECE "yüksek", "orta" veya \
   "düşük" değerlerinden biri olmalı. Başka değer kullanma; \
   "high"/"medium"/"low" gibi İngilizce karşılıklarını da yazma.
10. Müşteri yorumlarında ve kurum sözlüğünde geçen alan terimlerini \
    BİREBİR koru; eş anlamlı/yakın kelimeyle değiştirme (örn. "çok \
    parçalı gönderi"yi "çok kaplı" yapma).
"""

# ---------------------------------------------------------------------------
# User prompt template (Jinja2)
# ---------------------------------------------------------------------------

SWOT_USER_PROMPT_TEMPLATE = """\
ŞİRKET BAĞLAMI:
- Sektör: {{ industry_label }}{% if industry_other_text %} ({{ industry_other_text }}){% endif %}
- Büyüklük: {{ company_size_label }}
{% if business_description %}- İş tanımı: {{ business_description }}
{% endif %}
ANALİZ DÖNEMİ:
{% if date_from and date_to %}{{ date_from }} – {{ date_to }}{% else %}Tüm zaman{% endif %}

İSTATİSTİKLER:

[Genel]
- Toplam yorum: {{ total_reviews }}
- Ortalama duygu skoru: {% if avg_sentiment_score is not none %}{{ "%.2f"|format(avg_sentiment_score) }}{% else %}veri yok{% endif %} (-1.0 ile +1.0 arası)
- Kriz seviyesindeki yorum sayısı: {{ crisis_count }} (skor ≤ -0.80)
- Hassas konu içeren yorum sayısı: {{ sensitive_topics_count }}

[Duygu Dağılımı]
- Negatif: {{ sentiment_distribution.negative }}
- Nötr: {{ sentiment_distribution.neutral }}
- Pozitif: {{ sentiment_distribution.positive }}

[NPS]
{% if nps_score is not none %}\
- NPS skoru: {{ "%.1f"|format(nps_score) }}
- Kapsama: %{{ "%.1f"|format(nps_coverage_percent) }}
- Dağılım: Detractor {{ nps_distribution.detractor }}, Passive {{ nps_distribution.passive }}, Promoter {{ nps_distribution.promoter }}
{% else %}\
- NPS verisi henüz yetersiz (analiz yapılamıyor)
{% endif %}

[En Sık Geçen Kategoriler (BERT)]
{% for cat in category_distribution[:5] %}\
- {{ cat.code }}: {{ cat.count }} yorum (%{{ "%.1f"|format(cat.pct) }})
{% endfor %}

[En Sık Şirket Perspektifleri (Heuristik)]
{% for p in company_perspective_distribution[:7] %}\
- {{ p.label_tr }}: {{ p.count }} yorum (%{{ "%.1f"|format(p.pct) }})
{% endfor %}\
{% if unmatched_perspective_count > 0 %}
- (Eşleşmeyen: {{ unmatched_perspective_count }} yorum)
{% endif %}

Lütfen yukarıdaki bağlam ve verileri kullanarak SWOT analizi ve stratejik \
öneriler üret. response_schema'ya tam uyumlu JSON yanıtla.
"""

# Pre-compile the Jinja env once. StrictUndefined surfaces missing keys
# loudly instead of silently rendering "" — a regression in the
# StatsAggregator's snapshot shape would otherwise produce a
# coherent-looking but partially-empty prompt.
_jinja_env = Environment(
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
)
_swot_template = _jinja_env.from_string(SWOT_USER_PROMPT_TEMPLATE)


def render_swot_user_prompt(context: dict[str, Any]) -> str:
    """Render the SWOT user prompt with the given context dict.

    Expected keys (every one is required — the StrictUndefined Jinja
    env will throw if any are missing):

      * industry_label, industry_other_text (str | None),
        company_size_label, business_description (str | None)
      * date_from, date_to (date | None — Jinja stringifies via
        ISO format implicitly through ``str()``)
      * total_reviews, crisis_count, sensitive_topics_count
      * avg_sentiment_score (float | None)
      * sentiment_distribution: dict with negative/neutral/positive
      * nps_score (float | None), nps_coverage_percent (float),
        nps_distribution (dict with detractor/passive/promoter)
      * category_distribution: list[{code, count, pct}]
      * company_perspective_distribution: list[{label_tr, count, pct}]
      * unmatched_perspective_count: int

    The shape mirrors ``StrategicStatsSnapshot`` 1:1; the SWOT service
    builds the dict from the snapshot before calling.
    """
    # Jinja's ``date`` filter would handle date → string but we keep
    # the API explicit: pre-stringify ISO dates so the prompt sees
    # ``"2026-04-01"`` instead of relying on ``str(date(...))``
    # platform behaviour.
    ctx = dict(context)
    if isinstance(ctx.get("date_from"), _date):
        ctx["date_from"] = ctx["date_from"].isoformat()
    if isinstance(ctx.get("date_to"), _date):
        ctx["date_to"] = ctx["date_to"].isoformat()
    return _swot_template.render(**ctx)
