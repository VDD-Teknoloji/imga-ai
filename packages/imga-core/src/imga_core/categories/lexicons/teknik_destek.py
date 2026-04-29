"""Keywords for the 'Teknik Destek' category.

Covers: app/site faults, login problems, payment-step crashes, broken UI
flows. Cleaned of single-word noise ('sistem', 'şifre', 'çalışmıyor',
'error', 'bug', 'api') that triggered too broadly — only specific phrases
remain so that 'sistemde sorun' triggers but a stray 'sistem' word does not.
"""

from __future__ import annotations

TEKNIK_DESTEK_KEYWORDS: frozenset[str] = frozenset({
    # System / infrastructure
    "sistem hatası",
    "sistemde sorun",
    "sistem çalışmıyor",
    # Site / app crashes
    "site açılmıyor",
    "sayfa açılmıyor",
    "sayfa yenilenmiyor",
    "uygulama çöküyor",
    "uygulama açılmıyor",
    "uygulama donuyor",
    "çöküyor",
    "çöktü",
    "ekran donuyor",
    "ekran beyaz",
    # Errors
    "hata mesajı",
    "hata aldım",
    "hata veriyor",
    # Login / account
    "giriş yapamıyorum",
    "giriş yapamadım",
    "login",
    "şifre sıfırlama",
    "şifremi unuttum",
    "hesap engellendi",
    "hesap kilitlendi",
    # Cart / checkout flow
    "sepete ekleyemiyorum",
    "sepet boşaldı",
    "ödeme adımı",
    "check-out",
    "kart eklenmiyor",
    "adres eklenmiyor",
    # Media / scanning
    "video yüklenmiyor",
    "resim yüklenmiyor",
    "qr kod okumuyor",
    # App lifecycle
    "uygulama güncellemesi",
})
