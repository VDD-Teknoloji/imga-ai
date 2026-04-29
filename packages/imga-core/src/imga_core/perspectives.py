"""Customer- and company-perspective rule-based classifiers.

Hard-coded rules carried over verbatim from legacy/app.py:315-350. Smart-Rules
JSON engine (cx_rules.json) is intentionally omitted from this sprint.
"""

from __future__ import annotations

CUSTOMER_DEFAULT = "Memnuniyetsizlik / Bilgi Talebi"
COMPANY_DEFAULT = "Genel Operasyonel Aksaklık"


def classify_customer_perspective(text: str) -> str:
    """Return the customer-side intent label."""
    if not text:
        return "-"
    t = text.lower()

    if "iade" in t and ("istiyorum" in t or "talep" in t or "hakkım" in t):
        return "İade Talebi"
    if "değişim" in t and ("istiyorum" in t or "talep" in t or "hakkım" in t):
        return "Değişim Talebi"
    if "iptal" in t and ("istiyorum" in t or "etmeliyim" in t):
        return "İptal Talebi"
    if "ücret" in t and "iade" in t:
        return "Ücret İadesi Talebi"
    if "yetkili" in t and ("görüşmek" in t or "arıyorum" in t):
        return "Yetkiliyle Görüşme Talebi"
    if "çözüm" in t and ("bekliyorum" in t or "istiyorum" in t):
        return "Çözüm Beklentisi"
    if "mağdur" in t:
        return "Mağduriyet Giderimi"
    if "şikayetçiyim" in t:
        return "Resmi Şikayet"
    return CUSTOMER_DEFAULT


def classify_company_perspective(text: str) -> str:
    """Return the company-side root-cause label."""
    if not text:
        return "-"
    t = text.lower()

    if "değişim" in t and ("yok" in t or "red" in t or "kabul" in t or "yapılmadı" in t):
        return "Değişim Prosedürü / Stok"
    if "online" in t and ("mağaza" in t or "değişim" in t):
        return "Omnichannel (Online-Mağaza) Uyuşmazlığı"
    if any(w in t for w in ("ayıplı", "defolu", "kusurlu", "yırtık", "leke")):
        return "Ürün Kalite Kontrol (Defolu Gönderim)"
    if any(w in t for w in ("personel", "temsilci", "çalışan", "görevli")) and any(
        w in t for w in ("kaba", "saygısız", "ilgisiz", "bağırdı")
    ):
        return "Personel Davranışı / Eğitim"
    if any(w in t for w in ("kargo", "teslimat", "getirmedi")):
        return "Lojistik / Kargo Firması Hatası"
    if any(w in t for w in ("stok", "kalmadı", "temin")):
        return "Stok Yönetimi"
    if any(w in t for w in ("sistem", "hata", "açılmıyor")):
        return "Dijital Altyapı / IT Sorunu"
    if "yanlış" in t and ("bilgi" in t or "yönlendirme" in t):
        return "Hatalı Bilgilendirme"
    return COMPANY_DEFAULT
