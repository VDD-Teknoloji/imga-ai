"""Keywords for the 'Faturalama / Ödeme' category.

Cross-category-cleaned: refund-tied phrases ('iade tutarı', 'para iadesi',
'iade ödeme') live only in iade. This lexicon covers billing, payment,
charge, card, instalment, balance.
"""

from __future__ import annotations

FATURALAMA_KEYWORDS: frozenset[str] = frozenset({
    # Invoice
    "fatura",
    "faturam",
    "faturalandırma",
    "fatura kesilmedi",
    "fatura adresi",
    # Charge / fee
    "ücret",
    "ücretlendirme",
    "ücretlendirme hatası",
    "hatalı tutar",
    "tutar",
    "yanlış tutar",
    "fazla ücret",
    "çift çekim",
    "tahsilat",
    # Payment
    "ödeme",
    "ödeme alındı",
    "ödeme yapamadım",
    "geri ödeme yapılmadı",
    "kapora",
    "peşinat",
    # Money / balance
    "para",
    "para çekildi",
    "parayı geri",
    "hesap",
    "hesap kesildi",
    # Card / banking
    "banka",
    "kart",
    "kart bilgilerim",
    "kartım çekildi",
    "kredi kartı",
    "taksit",
    "komisyon",
    "havale",
    "eft",
    # Settlement state
    "yatmadı",
    "yansımadı",
})
