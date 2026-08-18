"""OKR v1 prompt + response schema.

Sprint 8.3.6 / Alt-Faz 8.3.6.4. Same module-resident pattern as
swot_v1.py: migration 0019 seeded a ``prompt_templates.template_key=
'okr_v1'`` placeholder row with ``is_active=false`` so the registry
table exists for future tenant overrides; OkrService reads the actual
prompt + schema from THIS file.

Differences from SWOT:

  * Input is a SWOT report's ``output_payload`` (strengths /
    weaknesses / opportunities / threats / strategic_recommendations),
    NOT a raw stats snapshot. The user prompt loops over those four
    SWOT arrays + the recommendations.
  * The schema is OKR-shaped: a list of objectives, each with a
    rationale + 2-4 SMART key results carrying baseline / target.
  * Defaults differ at the provider call site (temp 0.3 vs 0.2;
    max_output_tokens 4096 vs 8192).
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, StrictUndefined

# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

# Same Gemini SDK proto-Schema limitation as swot_v1: ``minItems`` /
# ``maxItems`` are unsupported and crash the SDK at validation time
# (8.3.6.6 round-1 production crash). The 2-4 / 2-4 spec lives in the
# system prompt with a permissive service-side guard that logs out-of-
# range counts but never rejects.
OKR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["objectives"],
    "properties": {
        "objectives": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["objective", "rationale", "key_results"],
                "properties": {
                    "objective": {"type": "string"},
                    "rationale": {"type": "string"},
                    "key_results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["text", "metric", "baseline", "target"],
                            "properties": {
                                "text": {"type": "string"},
                                "metric": {"type": "string"},
                                "baseline": {"type": "string"},
                                "target": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

OKR_SYSTEM_PROMPT = """\
Sen kıdemli bir iş stratejisi danışmanısın. Şirketlerin SWOT analizleri \
temelinde uygulanabilir OKR (Objectives and Key Results) önerileri \
hazırlıyorsun.

GÖREV:
Sana sunulan SWOT analizini temel alarak, önümüzdeki 12 hafta için 2-4 \
adet Objective öner. Her Objective için 2-4 adet ölçülebilir Key Result \
ekle. Her bir KR için:
- text: KR ifadesi (kısa ve net)
- metric: hangi metrik takip edilecek
- baseline: mevcut değer (SWOT verisinden veya "ölçülmüyor")
- target: 12 hafta sonunda ulaşılmak istenen değer

KURALLAR:
1. Her Objective ilham verici, somut ve 12 hafta odaklı olsun.
2. Her KR SMART formatta olsun (Specific, Measurable, Achievable, \
   Relevant, Time-bound).
3. rationale alanında her Objective'in hangi SWOT maddelerinden türediğini \
   belirt.
4. Sayı uydurma. Baseline alanına SWOT'tan gelen sayıları kullan veya \
   "ölçülmüyor" yaz.
5. KR'ler birbirinden farklı boyutları ölçsün — aynı şeyin iki ölçümünü \
   yazma.
6. Türkçe yaz. Hedefler net ve ulaşılabilir olsun.
7. JSON formatında, response_schema'ya tam uyumlu yanıt ver.
8. 2-4 Objective öner. Her Objective için 2-4 Key Result tanımla. Her KR \
   ölçülebilir ve farklı bir boyutu kapsar olsun.
9. Müşteri yorumlarında ve kurum sözlüğünde geçen alan terimlerini \
   BİREBİR koru; eş anlamlı/yakın kelimeyle değiştirme (örn. "çok \
   parçalı gönderi"yi "çok kaplı" yapma).
"""

# ---------------------------------------------------------------------------
# User prompt template (Jinja2)
# ---------------------------------------------------------------------------

OKR_USER_PROMPT_TEMPLATE = """\
SWOT ANALİZİ ÖZETİ:

[Güçlü Yönler]
{% for s in strengths %}\
- {{ s.title }}: {{ s.description }} (Kanıt: {{ s.evidence }})
{% endfor %}
[Zayıf Yönler]
{% for w in weaknesses %}\
- {{ w.title }}: {{ w.description }} (Kanıt: {{ w.evidence }})
{% endfor %}
[Fırsatlar]
{% for o in opportunities %}\
- {{ o.title }}: {{ o.description }} (Kanıt: {{ o.evidence }})
{% endfor %}
[Tehditler]
{% for t in threats %}\
- {{ t.title }}: {{ t.description }} (Kanıt: {{ t.evidence }})
{% endfor %}
[Stratejik Öneriler]
{% for r in strategic_recommendations %}\
- {{ r.title }} ({{ r.priority }} öncelik, {{ r.estimated_impact }} etki): {{ r.description }}
{% endfor %}
ŞİRKET BAĞLAMI:
- Sektör: {{ industry_label }}
- Büyüklük: {{ company_size_label }}

Bu SWOT temelinde önümüzdeki 12 hafta için 2-4 Objective ve her birine \
2-4 Key Result öner. response_schema'ya tam uyumlu JSON yanıtla.
"""

_jinja_env = Environment(
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
)
_okr_template = _jinja_env.from_string(OKR_USER_PROMPT_TEMPLATE)


def render_okr_user_prompt(context: dict[str, Any]) -> str:
    """Render the OKR user prompt with the given context dict.

    Required keys:
      * strengths, weaknesses, opportunities, threats — each a list of
        ``{title, description, evidence}`` objects (the SWOT payload's
        first four sections).
      * strategic_recommendations — list of
        ``{title, description, priority, estimated_impact}`` objects.
      * industry_label, company_size_label — resolved Türkçe labels
        from the source SWOT's input_stats (industry +
        industry_other_text + company_size).

    StrictUndefined surfaces a missing key loudly — a regression in the
    SWOT payload shape would otherwise produce a coherent-looking but
    partial OKR prompt.
    """
    return _okr_template.render(**context)
