"""Kalite raporu özeti v1 — sistem prompt'u + kullanıcı prompt'u + şema.

2026-08-18 (migration 0042) "büyük paket" WS2. Bir batch job'ın veri
kalitesi bayrak sayaçları + en çok tekrarlanan metinler + çalışan bazlı
kırılım modele verilir; TEK bir kısa Türkçe değerlendirme (~200-300
kelime: nedenler + öneriler) istenir. ``root_cause_v1`` / ``swot_v1``
ile aynı modül-yerleşik desen (Jinja2 kullanıcı prompt'u, sabit sistem
prompt'u, structured-output şeması).

``QualityReportService`` bu şemayı ``generate_root_cause`` (imga_core
GeminiProvider/OpenRouterProvider) üzerinden çağırır — o metod
``_generate_structured``'a ince bir sarmalayıcıdır ve response_schema
tamamen serbest, yani "kök neden" adı burada yanıltıcı değil, sadece
mevcut generic structured-output vekilidir (imga-core'a yeni bir
`generate_quality_report` metodu eklemek migration'sız da mümkündü
ama mevcut vekillerden birini kullanmak imga-core'a hiç dokunmadan
aynı sonucu verir — bkz. WS2 iş bölümü: bu dalga imga-core'a dokunmaz).
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, StrictUndefined

# ---------------------------------------------------------------------------
# Response schema (structured output)
# ---------------------------------------------------------------------------

QUALITY_REPORT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["assessment"],
    "properties": {
        "assessment": {
            "type": "string",
            "description": (
                "200-300 kelimelik Türkçe değerlendirme: bayrakların "
                "muhtemel nedenleri + somut öneriler."
            ),
        },
    },
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

QUALITY_REPORT_SYSTEM_PROMPT = """\
Sen müşteri deneyimi (CX) veri operasyonlarında veri kalitesi analisti \
olarak çalışıyorsun. Sana TEK bir toplu yükleme işinin (batch job) veri \
kalitesi istatistikleri verilir: kaç satırın kopya/boş/şablon-bildirimi/ \
anlamsız olarak işaretlendiği, en çok tekrarlanan metinler ve varsa \
çalışan bazlı kırılım.

GÖREV:
``assessment`` alanına 200-300 kelimelik TEK bir Türkçe değerlendirme \
yaz. İçeriği:
1. Bayrakların büyüklüğüne göre EN olası 1-3 neden (örn. "aynı şablon \
   metni birden çok kez yapıştırılmış", "otomatik e-posta bildirimleri \
   yorum olarak yüklenmiş", "belirli bir çalışanın girdiği satırlarda \
   kopya oranı yüksek").
2. Somut, uygulanabilir 1-3 öneri (örn. "yükleme öncesi X şablonunu \
   filtreleyin", "Y çalışanıyla veri girişi sürecini gözden geçirin").

KURALLAR:
1. Yalnız SANA VERİLEN sayılara ve örneklere dayan; uydurma bir olgu \
   ekleme.
2. Sayıları tekrar tekrar sıralama (kullanıcı zaten sayaçları görüyor); \
   yorumla.
3. Bayrak sayıları düşükse ("veri kalitesi iyi görünüyor" gibi) bunu \
   kısaca belirt, yapay bir sorun uydurma.
4. Türkçe, resmi ama sade bir dil kullan.
5. JSON formatında, response_schema'ya tam uyumlu yanıt ver.
"""

# ---------------------------------------------------------------------------
# User prompt template (Jinja2)
# ---------------------------------------------------------------------------

QUALITY_REPORT_USER_PROMPT_TEMPLATE = """\
İŞ ÖZETİ:
- Toplam işlenen satır: {{ total_rows }}
- Başarılı satır: {{ succeeded_rows }}

BAYRAK SAYAÇLARI:
- Kopya (duplicate): {{ quality_duplicate_rows }}
- Boş (empty): {{ quality_empty_rows }}
- Şablon/otomasyon bildirimi (informational): {{ quality_informational_rows }}
- Anlamsız/düşük içerik (meaningless): {{ quality_meaningless_rows }}

EN ÇOK TEKRARLANAN METİNLER (ilk {{ top_repeated_texts|length }}):
{% for r in top_repeated_texts %}\
{{ loop.index }}. ({{ r.count }} kez) {{ r.sample_text }}
{% endfor %}
{% if not top_repeated_texts %}(tekrarlanan metin yok)
{% endif %}

ÇALIŞAN BAZLI KIRILIM (entered_by, ilk {{ entered_by_breakdown|length }}):
{% for e in entered_by_breakdown %}\
{{ loop.index }}. {{ e.entered_by or "(belirtilmemiş)" }} — toplam \
{{ e.total }}, kopya {{ e.duplicate }}, boş {{ e.empty }}, \
şablon {{ e.informational }}, anlamsız {{ e.meaningless }}
{% endfor %}
{% if not entered_by_breakdown %}(çalışan bilgisi yok)
{% endif %}

Yukarıdaki istatistiklere dayanarak response_schema'ya tam uyumlu JSON \
yanıtla.
"""

_jinja_env = Environment(
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
)
_quality_report_template = _jinja_env.from_string(
    QUALITY_REPORT_USER_PROMPT_TEMPLATE
)


def render_quality_report_user_prompt(context: dict[str, Any]) -> str:
    """Render the quality-report user prompt.

    Expected keys (all required — StrictUndefined enforces):

      * total_rows, succeeded_rows (int)
      * quality_duplicate_rows, quality_empty_rows,
        quality_informational_rows, quality_meaningless_rows (int)
      * top_repeated_texts: list[{"count": int, "sample_text": str}]
      * entered_by_breakdown: list[{"entered_by": str | None, "total": int,
        "duplicate": int, "empty": int, "informational": int,
        "meaningless": int}]
    """
    return _quality_report_template.render(**context)


__all__ = [
    "QUALITY_REPORT_RESPONSE_SCHEMA",
    "QUALITY_REPORT_SYSTEM_PROMPT",
    "QUALITY_REPORT_USER_PROMPT_TEMPLATE",
    "render_quality_report_user_prompt",
]
