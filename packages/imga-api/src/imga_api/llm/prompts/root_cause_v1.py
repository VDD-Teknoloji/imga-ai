"""Kök neden analizi v1 — sistem prompt'u + kullanıcı prompt'u + şema.

Sprint 13.1. Hiyerarşik kategori drill-down'ın üçüncü seviyesi:
kullanıcı bir alt kategoriye (ör. "Siparişimin statüsü doğru değil")
tıkladığında o kovadaki ham yorumlar modele verilir ve "nokta atışı"
kök nedenler istenir.

Modül-yerleşik (DB-yerleşik değil), swot_v1 / executive_briefing_v1
ile aynı desen. Kullanıcı prompt'u Jinja2 çünkü yorum listesi bir
döngü ve tarih penceresi koşullu.

ŞEMA NOTU: ``share_estimate_pct`` bilinçli olarak ``required``
DIŞINDA. Gemini SDK'sının proto Schema tipi ``minItems``/``maxItems``
gibi anahtarlarda 400 attığı için (bkz. swot_v1 tarihçesi) sayısal
sınırlar sistem prompt'unda yaşıyor; aynı temkinle "bilinmiyorsa
alanı hiç yazma" talimatı veriliyor ve servis eksik alanı None'a
düşürüyor.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any

from jinja2 import Environment, StrictUndefined

# ---------------------------------------------------------------------------
# Response schema (structured output)
# ---------------------------------------------------------------------------

ROOT_CAUSE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "root_causes"],
    "properties": {
        "summary": {"type": "string"},
        "root_causes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "title",
                    "description",
                    "evidence_quotes",
                    "affected_surface",
                    "suggested_action",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence_quotes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "affected_surface": {"type": "string"},
                    "suggested_action": {"type": "string"},
                    "share_estimate_pct": {"type": "number"},
                },
            },
        },
    },
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

ROOT_CAUSE_SYSTEM_PROMPT = """\
Sen müşteri deneyimi (CX) operasyonlarında kök neden analizi yapan kıdemli \
bir analistsin. Sana TEK bir şikâyet kovasındaki ham müşteri yorumları \
verilir; görevin bu yorumların ARKASINDAKİ operasyonel nedeni bulmaktır.

GÖREV:
Yorumları oku ve 1-5 adet kök neden çıkar. Her kök neden için:
- title: kök nedenin kısa adı (5-10 kelime)
- description: mekanizmayı anlat — hangi adım, nerede, neden bozuluyor \
  (2-4 cümle)
- evidence_quotes: bu nedeni destekleyen EN FAZLA 3 alıntı. Alıntılar \
  sana verilen yorumlardan BİREBİR olmalı; kısaltabilirsin ama \
  yeniden yazamazsın.
- affected_surface: sorunun yaşandığı temas noktası \
  (örn. "mobil uygulama", "e-posta bilgilendirmesi", "kargo takip \
  ekranı", "çağrı merkezi")
- suggested_action: sahibi belli, somut tek bir düzeltme önerisi. Yeni bir \
  ekran ya da özellik inşa etmeyi önerme; var olan bir kanaldan (SMS, \
  e-posta, çağrı merkezi scripti, iç süreç talimatı) BU HAFTA \
  başlatılabilecek, sahibi belli somut bir adım öner.
- share_estimate_pct: bu kök nedenin kovadaki yorumların yüzde kaçını \
  açıkladığına dair tahmin (0-100). Tahmin edemiyorsan bu alanı HİÇ \
  YAZMA.

KURALLAR:
1. Yorumlarda olmayan bir olgu UYDURMA. Elinde kanıt yoksa o kök nedeni verme.
2. Semptomu değil NEDENİ yaz. "Müşteriler kızgın" bir kök neden değildir; \
   "uygulama kargo statüsünü teslim edilmiş gösteriyor, müşteri ancak \
   çağrı merkezini arayınca gerçeği öğreniyor" bir kök nedendir.
3. evidence_quotes alanını asla boş bırakma; en az 1, en fazla 3 alıntı ver.
4. Kök nedenler birbirinden AYRI olsun; aynı nedeni iki başlıkla yazma.
5. En çok yorumu açıklayan kök nedeni ilk sıraya koy.
6. En az 1, en fazla 5 kök neden döndür.
7. summary alanında kovanın bütününü 2-3 cümlede özetle.
8. JSON formatında, response_schema'ya tam uyumlu yanıt ver.
9. Müşteri yorumlarında ve kurum sözlüğünde geçen alan terimlerini \
   BİREBİR koru; eş anlamlı/yakın kelimeyle değiştirme (örn. "çok \
   parçalı gönderi"yi "çok kaplı" yapma) — evidence_quotes zaten \
   birebir alıntı ister, bu kural title/description/suggested_action \
   gibi serbest metin alanlarını da aynı disipline sokar.
"""

# ---------------------------------------------------------------------------
# User prompt template (Jinja2)
# ---------------------------------------------------------------------------

ROOT_CAUSE_USER_PROMPT_TEMPLATE = """\
ANA KATEGORİ: {{ primary_category_label }}
ALT KATEGORİ: {{ perspective_label }}
ANALİZ DÖNEMİ: {% if date_from and date_to %}{{ date_from }} – {{ date_to }}\
{% else %}Tüm zaman{% endif %}

KOVA İSTATİSTİĞİ:
- Bu kovadaki toplam yorum: {{ bucket_total }}
- Bunlardan olumsuz olan: {{ bucket_negative }}
- Aşağıda örneklenen yorum sayısı: {{ sample_count }} \
(önce NEGATİF, sonra en yeniler)

MÜŞTERİ YORUMLARI:
{% for r in reviews %}\
{{ loop.index }}. [{{ r.sentiment }}] {{ r.text }}
{% endfor %}

Yukarıdaki yorumların ARKASINDAKİ operasyonel kök nedenleri çıkar. \
response_schema'ya tam uyumlu JSON yanıtla.
"""

# StrictUndefined: eksik bir context anahtarı sessizce "" render
# etmek yerine yüksek sesle patlasın (swot_v1 ile aynı gerekçe).
_jinja_env = Environment(
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
)
_root_cause_template = _jinja_env.from_string(ROOT_CAUSE_USER_PROMPT_TEMPLATE)


def render_root_cause_user_prompt(context: dict[str, Any]) -> str:
    """Render the root-cause user prompt.

    Expected keys (all required — StrictUndefined enforces):

      * primary_category_label, perspective_label (str)
      * date_from, date_to (date | str | None)
      * bucket_total, bucket_negative, sample_count (int)
      * reviews: list[{"text": str, "sentiment": str}]
    """
    ctx = dict(context)
    if isinstance(ctx.get("date_from"), _date):
        ctx["date_from"] = ctx["date_from"].isoformat()
    if isinstance(ctx.get("date_to"), _date):
        ctx["date_to"] = ctx["date_to"].isoformat()
    return _root_cause_template.render(**ctx)


__all__ = [
    "ROOT_CAUSE_RESPONSE_SCHEMA",
    "ROOT_CAUSE_SYSTEM_PROMPT",
    "ROOT_CAUSE_USER_PROMPT_TEMPLATE",
    "render_root_cause_user_prompt",
]
