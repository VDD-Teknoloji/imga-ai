"""Executive briefing v1 prompt + response schema.

Sprint 8.3.10. Module-resident prompt (Sprint 8.3.6 pattern) — the
DB ``prompt_templates`` registry is the future home, but until it's
wired in for tenant overrides the source of truth lives here.

Output contract — must match ExecutiveBriefingResponse.headline /
kpi_changes / critical_insights / top_actions. The Gemini SDK
schema enforces ``type: "string"`` on enum fields (Sprint 8.3.6.6
round-3 lesson).
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, StrictUndefined

EXECUTIVE_BRIEFING_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["headline", "kpi_changes", "critical_insights", "top_actions"],
    "properties": {
        "headline": {"type": "string"},
        "kpi_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["metric", "current", "previous", "change_pct", "direction"],
                "properties": {
                    "metric": {"type": "string"},
                    "current": {"type": "number"},
                    "previous": {"type": "number"},
                    "change_pct": {"type": "number"},
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "flat"],
                    },
                },
            },
        },
        "critical_insights": {
            "type": "array",
            "items": {"type": "string"},
        },
        "top_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "rationale"],
                "properties": {
                    "title": {"type": "string"},
                    "rationale": {"type": "string"},
                },
            },
        },
    },
}


EXECUTIVE_BRIEFING_SYSTEM_PROMPT = """\
Sen kıdemli bir CX yöneticisi danışmanısın. Türkiye'deki şirketler için \
veri-odaklı, kısa ve eyleme dönüştürülebilir yönetici özetleri \
hazırlıyorsun.

GÖREV:
Sana sunulan dönem istatistikleri ve önceki dönemle karşılaştırmalı \
veriyi kullanarak bir yönetici brifingi oluştur:

- headline: 1 cümle (max 30 kelime), dönemin ana mesajı.
- kpi_changes: 3-5 kritik metrik değişimi (current vs previous + \
  change_pct + direction='up'/'down'/'flat').
- critical_insights: 2-3 kritik içgörü; her biri 1-2 cümle.
- top_actions: 3 öncelikli aksiyon; her birinde title + rationale.

KURALLAR:
1. Sayı uydurma. Sadece sana verilen istatistikleri kullan.
2. Türkçe yaz. Profesyonel ama kısa, yöneticiye uygun ton.
3. headline kısa olsun (max 30 kelime, 1 cümle).
4. kpi_changes 'direction' alanı SADECE 'up', 'down' veya 'flat' \
   değerlerinden biri olmalı. Başka değer yazma.
5. JSON formatında, response_schema'ya tam uyumlu yanıt ver.
"""


EXECUTIVE_BRIEFING_USER_PROMPT_TEMPLATE = """\
ŞİRKET BAĞLAMI:
- Sektör: {{ industry_label }}
- Büyüklük: {{ company_size_label }}

DÖNEM BİLGİSİ:
- Dönem türü: {{ period_label }}
- Aralık: {{ date_from }} – {{ date_to }}
{% if batch_label %}- Yükleme: {{ batch_label }}{% endif %}

MEVCUT DÖNEM:
- Toplam yorum: {{ current.total_reviews }}
- NPS: {% if current.nps_score is not none %}{{ "%.1f"|format(current.nps_score) }}{% else %}veri yok{% endif %}
- Ortalama duygu: {% if current.avg_sentiment is not none %}{{ "%.2f"|format(current.avg_sentiment) }}{% else %}veri yok{% endif %}
- Negatif yorum oranı: %{{ "%.1f"|format(current.negative_share * 100) }}
- Top kategoriler:
{% for cat in current.top_categories %}  - {{ cat.label }}: {{ cat.count }} yorum
{% endfor %}

ÖNCEKİ DÖNEM:
- Toplam yorum: {{ previous.total_reviews }}
- NPS: {% if previous.nps_score is not none %}{{ "%.1f"|format(previous.nps_score) }}{% else %}veri yok{% endif %}
- Ortalama duygu: {% if previous.avg_sentiment is not none %}{{ "%.2f"|format(previous.avg_sentiment) }}{% else %}veri yok{% endif %}
- Negatif yorum oranı: %{{ "%.1f"|format(previous.negative_share * 100) }}

Yukarıdaki veriyle yönetici brifingi üret. response_schema'ya tam \
uyumlu JSON yanıtla.
"""


_jinja_env = Environment(
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
)
_template = _jinja_env.from_string(EXECUTIVE_BRIEFING_USER_PROMPT_TEMPLATE)


def render_executive_briefing_user_prompt(context: dict[str, Any]) -> str:
    """Render the user prompt. Required keys mirror the
    ExecutiveBriefingService snapshot helper."""
    return _template.render(**context)


__all__ = [
    "EXECUTIVE_BRIEFING_RESPONSE_SCHEMA",
    "EXECUTIVE_BRIEFING_SYSTEM_PROMPT",
    "render_executive_briefing_user_prompt",
]
