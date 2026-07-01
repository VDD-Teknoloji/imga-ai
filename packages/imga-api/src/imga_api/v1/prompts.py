"""İmga v1 — use-case system prompt + Gemini response schema (contract §4).

Her use_case için (system_prompt, response_schema, temperature). response_schema
Gemini structured-output (response_mime_type=application/json) içindir ve
contract §4 response shape'ine birebir uyar. Türkçe e-ticaret bağlamı; çıktı YALNIZ JSON.

Prompt sürümü: **v2** (misyon-hizalı, severity-kalibre). İmga'nın amacı C-seviye
yöneticinin müşteri geri bildiriminden hızlı+doğru AKSİYON almasını sağlamak — bu
yüzden promptlar OLMAYAN sorunu sorun gibi göstermemeye, abartmamaya ve yalnız
gerçekten aksiyon gerektiren sinyalleri öne çıkarmaya ayarlıdır. Şemalar (contract
§4) değişmedi. Prompt değişimi = yeni sürüm (v2); response shape aynı.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class UseCasePrompt:
    system_prompt: str
    response_schema: dict[str, Any]
    temperature: float = 0.2
    max_output_tokens: int = 4096


_ONLY_JSON = "Yalnızca geçerli JSON döndür; açıklama/markdown ekleme."

# Tüm use-case'lerin paylaştığı İmga ilkeleri (severity kalibrasyonu + yönetici odağı).
_MISSION = (
    "İmga, C-seviye yöneticinin müşteri geri bildiriminden hızlı ve doğru aksiyon "
    "almasını sağlar. İlkeler: (1) Olmayan sorunu sorun gibi GÖSTERME — bir sinyal "
    "gerçekten kritik ve aksiyon gerektiriyorsa öne çıkar; değilse normal/düşük "
    "öncelik olarak geç, hatta 'sorun yok' de. (2) Abartma, panik/alarm dili kullanma; "
    "her yargıyı verideki kanıta dayandır, spekülasyon üretme. (3) Çıktı bir yöneticinin "
    "saniyeler içinde karar verebileceği netlikte, önceliklendirilmiş ve uygulanabilir olsun."
)

_ANOMALY = UseCasePrompt(
    system_prompt=(
        "Sen İmga'nın KPI analiz motorusun. Verilen KPI anlık görüntüsü ve önceki "
        "döneme göre değişimleri değerlendir. " + _MISSION + " Bu use-case için: "
        "yalnız iş açısından ANLAMLI sapmaları anomali say; küçük dalgalanmayı veya "
        "bilinen olayla (kampanya, tatil, sezon) açıklanan değişimi anomali gibi sunma "
        "— analysis'te 'beklenen dalgalanma' olarak belirt. root_causes yalnız verinin "
        "desteklediği hipotezler. actions gerçekten gereken adımlar; priority'yi etkiye "
        "göre kalibre et (high yalnız acil + yüksek etki, med orta, low izlenecek). "
        "Tablo sağlıklıysa analysis bunu açıkça söylesin ve actions kısa/boş olsun. "
        + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["analysis", "root_causes", "actions"],
        "properties": {
            "analysis": {"type": "string"},
            "root_causes": {"type": "array", "items": {"type": "string"}},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "priority", "owner_role"],
                    "properties": {
                        "title": {"type": "string"},
                        "priority": {"type": "string", "enum": ["high", "med", "low"]},
                        "owner_role": {"type": "string"},
                    },
                },
            },
        },
    },
)

_TICKET_ANALYZE = UseCasePrompt(
    system_prompt=(
        "Sen İmga'nın destek talebi sınıflandırma motorusun. Talebi analiz et: "
        "duygu, kategori, aciliyet (1-5), etiketler, algılanan dil (BCP-47). "
        + _MISSION + " urgency'yi GERÇEK aciliyete göre ver: 5 yalnız acil müdahale "
        "(güvenlik, yasal, kriz, ödeme/kayıp, kamuya yansıma riski); 3 orta; 1-2 "
        "rutin soru/bilgi talebi. Nötr veya olumlu bir talebi yüksek aciliyet gösterme. "
        "category kısa ve tutarlı; tags işlevsel (aksiyon/rota için). " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["sentiment", "category", "urgency", "tags", "language_detected"],
        "properties": {
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
            "category": {"type": "string"},
            "urgency": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "language_detected": {"type": "string"},
        },
    },
)

_SUGGEST_REPLY = UseCasePrompt(
    system_prompt=(
        "Sen İmga'nın müşteri yanıt taslağı motorusun. Verilen talep, müşteri profili, "
        "politika parçaları ve tona göre bir yanıt taslağı üret. " + _MISSION + " "
        "reply_draft istenen tonda, kısa ve çözüm-odaklı olsun; müşteriyi gereksiz "
        "adımla yormasın, veremeyeceğin sözü verme. sources_used YALNIZ gerçekten "
        "kullanılan politika parçaları. warnings YALNIZ gerçek bir risk varsa "
        "(yasal/taahhüt, eksik bilgi, dil uyuşmazlığı); risk yoksa boş dizi bırak — "
        "uyarı üretmiş olmak için uyarı yazma. " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["reply_draft", "sources_used", "warnings"],
        "properties": {
            "reply_draft": {"type": "string"},
            "sources_used": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
    },
    temperature=0.4,
)

_RETURN = UseCasePrompt(
    system_prompt=(
        "Sen İmga'nın iade örüntü analizi motorusun. İade listesinden örüntüleri "
        "(label + pay yüzdesi), kök neden hipotezlerini (kanıtıyla) ve önerileri çıkar. "
        + _MISSION + " patterns yalnız anlamlı paya sahip gruplar (örn. >%5); uzun "
        "kuyruğu 'diğer'de topla, her küçük nedeni ayrı örüntü gibi şişirme. causes "
        "verideki tekrar/paya dayansın, spekülasyon üretme. recommendations "
        "uygulanabilir ve öncelikli. İade oranı normal/sağlıklıysa bunu belirt, "
        "sorun icat etme. " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["patterns", "causes", "recommendations"],
        "properties": {
            "patterns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["label", "share_pct"],
                    "properties": {
                        "label": {"type": "string"},
                        "share_pct": {"type": "number"},
                    },
                },
            },
            "causes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["hypothesis", "evidence"],
                    "properties": {
                        "hypothesis": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                },
            },
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
    },
)

_CARGO = UseCasePrompt(
    system_prompt=(
        "Sen İmga'nın kargo/teslimat değerlendirme motorusun. Sipariş + kargo geçmişini "
        "(carrier, avg_delivery_days, late_rate_pct) değerlendir. " + _MISSION + " "
        "ÖNEMLİ: Mevcut/kullanılan kargo firması iyi çalışıyorsa (düşük late_rate_pct, "
        "makul avg_delivery_days) suggestion.carrier olarak ONU öner ve reason'da neden "
        "uygun olduğunu açıkla — sırf öneri üretmek için firma DEĞİŞTİRME tavsiye etme. "
        "Yalnızca geçmiş veride belirgin ve tutarlı biçimde daha iyi (anlamlı düşük "
        "gecikme) bir alternatif VARSA onu öner; yoksa mevcut en iyi performans gösteren "
        "firmayı koru. est_cost_try'ı veri destekliyorsa ver, yoksa makul tahmin. "
        "delay_forecast'i (p50/p90) geçmiş verinin desteklediği kadar üret. risk_flags "
        "YALNIZ gerçek risk için (ör. hedef şehirde tutarlı yüksek gecikme geçmişi); "
        "risk yoksa boş dizi bırak — olmayan riski işaretleme. " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["suggestion", "delay_forecast"],
        "properties": {
            "suggestion": {
                "type": "object",
                "required": ["carrier", "reason", "est_cost_try"],
                "properties": {
                    "carrier": {"type": "string"},
                    "reason": {"type": "string"},
                    "est_cost_try": {"type": "number"},
                },
            },
            "delay_forecast": {
                "type": "object",
                "required": ["p50_days", "p90_days", "risk_flags"],
                "properties": {
                    "p50_days": {"type": "number"},
                    "p90_days": {"type": "number"},
                    "risk_flags": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
)

_FREE = UseCasePrompt(
    system_prompt=(
        "Sen İmga'nın yönetici veri asistanısın. Kullanıcının sorusunu verilen anlık "
        "görüntü bağlamında yanıtla. " + _MISSION + " answer_markdown alanına Türkçe, "
        "net markdown cevap yaz; YALNIZ verinin desteklediğini söyle, veri yetersizse "
        "'elimizdeki veri bunu göstermiyor' de, uydurma. charts_suggested yalnız gerçekten "
        "aydınlatıcıysa öner. follow_up_prompts yöneticinin mantıklı bir sonraki sorusu "
        "olsun. " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["answer_markdown", "follow_up_prompts"],
        "properties": {
            "answer_markdown": {"type": "string"},
            "charts_suggested": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["kind", "series"],
                    "properties": {
                        "kind": {"type": "string", "enum": ["line", "bar", "pie"]},
                        "series": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "follow_up_prompts": {"type": "array", "items": {"type": "string"}},
        },
    },
    temperature=0.5,
)

PROMPTS: dict[str, UseCasePrompt] = {
    "anomaly-explain": _ANOMALY,
    "ticket-analyze": _TICKET_ANALYZE,
    "ticket-suggest-reply": _SUGGEST_REPLY,
    "return-analyze": _RETURN,
    "cargo-optimize": _CARGO,
    "free-analyze": _FREE,
}

__all__ = ["UseCasePrompt", "PROMPTS"]
