"""Keywords for the 'Müşteri Hizmetleri' category.

Covers: phone / call-center / chat support, agent behaviour, response delays,
escalation requests.
"""

from __future__ import annotations

MUSTERI_HIZMETLERI_KEYWORDS: frozenset[str] = frozenset({
    # Channel
    "müşteri hizmetleri",
    "müşteri temsilcisi",
    "müşteri hizmetlerine",
    "çağrı merkezi",
    "şikayet hattı",
    "canlı destek",
    "chat",
    "whatsapp destek",
    "iletişim formu",
    # Phone state
    "telefon açmadı",
    "telefonu kapattı",
    "aradım açan yok",
    "aradım ulaşamadım",
    "ulaşılmıyor",
    "ulaşamıyorum",
    "bağlanamıyorum",
    "hatta bekledim",
    "dakikalarca bekledim",
    "meşgul",
    "kapatıyor",
    # Response delays
    "cevap vermiyor",
    "dönüş yapmadı",
    "dönüş yok",
    "geri arama yok",
    "mesajıma cevap",
    # Agent quality
    "temsilci kaba",
    "temsilci ilgisiz",
    "personel saygısız",
    "personel kaba",
    "argo kullandı",
    "azarladı",
    "terbiyesizce",
    "bilgisiz",
    "yetersiz personel",
    "profesyonelce değil",
    "çözüm sunmadı",
    # Escalation
    "yetkili istedim",
    "yetkiliyle görüşemedim",
    "yöneticiyi istedim",
    "manager",
})
