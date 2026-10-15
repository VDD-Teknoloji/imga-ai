"""Müşteri yolculuğu aşaması — yorum başına birleşik motor kararı.

Aşama, yorumu yazan kişinin markayla ilişkisinde O ANDA bulunduğu
noktadır (huni sırası: keşif → değerlendirme → satın alma → teslimat/
başlangıç → kullanım → destek → sadakat → ayrılma). Kategoriden ya da
duygudan TÜRETİLMEZ; ``experience_type`` ile aynı desende ayrı bir LLM
alanıdır ("j"). Kodlar ``ck_reviews_journey_stage`` (migration 0052)
ile birebir aynı — buradaki demet tek kaynak.

Twitter çekimleri yazar kimliği taşımaz (KVKK, bkz. twitter_import);
bu yüzden aşama müşteri başına değil yorum başına tutulur ve müşteri
kayıtlarına yalnız ``customer_external_id`` bağlı yorumlardan yayılır.
"""

from __future__ import annotations

JOURNEY_STAGES: tuple[str, ...] = (
    "kesif",
    "degerlendirme",
    "satin_alma",
    "teslimat",
    "kullanim",
    "destek",
    "sadakat",
    "ayrilma",
)

JOURNEY_STAGE_SET: frozenset[str] = frozenset(JOURNEY_STAGES)

# Prompt'ta tekrar eden kod listesi; sistem istemi kurum bazında
# değiştirilebildiği için (prompt_templates) bu satır her zaman
# ``_build_prompt``'un sabit kuyruğunda da yer alır.
JOURNEY_STAGE_CODES_INLINE = "|".join(JOURNEY_STAGES)

# Aşama tanımları. Kurum bazlı sistem istemi (prompt_templates) varsayılan
# istemi BÜTÜNÜYLE değiştirir; bu metin o yüzden ``_build_prompt``'un her
# zaman eklenen kuyruğunda durur — özel istemde bile model kodları anlamlı
# tanımlarıyla alır. Varsayılan istemdeki örnekler bunu tamamlar.
JOURNEY_STAGE_RULE = (
    "j (yolculuk aşaması) — yazarın markayla ilişkisinde bulunduğu nokta: "
    "kesif = markayı yeni duymuş / henüz müşteri değil, genel merak; "
    "degerlendirme = satın alma ÖNCESİ karşılaştırma, fiyat/özellik/kampanya/"
    "teslimat-bölgesi sorusu; satin_alma = sipariş verme, ödeme, sepet, sipariş "
    "onayı/hazırlık anı; teslimat = sipariş SONRASI teslimat, kurulum, aktivasyon, "
    "ilk kullanım; kullanim = düzenli kullanımdaki deneyim, ürün/hizmet/uygulama "
    "geri bildirimi; destek = açık bir sorun için destek, çağrı merkezi, iade/"
    "değişim süreciyle etkileşim; sadakat = tekrar alım, yenileme, tavsiye, uzun "
    "süreli memnuniyet; ayrilma = iptal, ilişkiyi bitirme, rakibe geçme niyeti ya "
    'da "bir daha almam" ifadesi. Aşama ≠ duygu: kullanimda negatif de olur; '
    "ayrilma YALNIZ niyet açıkça yazılmışsa. Belirlenemiyorsa j'yi HİÇ yazma."
)


def normalize_journey_stage(value: object) -> str | None:
    """LLM çıktısını DB sözleşmesine indirger: bilinmeyen/boş → None."""
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    return candidate if candidate in JOURNEY_STAGE_SET else None


__all__ = [
    "JOURNEY_STAGES",
    "JOURNEY_STAGE_CODES_INLINE",
    "JOURNEY_STAGE_RULE",
    "JOURNEY_STAGE_SET",
    "normalize_journey_stage",
]
