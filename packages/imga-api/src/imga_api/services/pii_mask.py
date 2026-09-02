"""KVKK — LLM çıktısındaki serbest metin için deterministik kişisel veri
maskesi (2026-09-02).

Kök neden kartlarındaki kanıt alıntıları ham müşteri yorumundan kelimesi
kelimesine geliyor; e-posta yazışmalarında gönderici/alıcı adı, telefon,
e-posta adresi olduğu gibi ekrana çıkıyordu. Asıl ad maskesini prompt
yapar (model kişi adlarını ``[ad]`` ile değiştirir — LLM'in NER'i
regex'ten çok daha isabetli). Bu modül onun ARKASINDAKİ emniyet ağı:
modelin kaçırdığı e-posta / telefon / TCKN / IBAN'ı ve birkaç yüksek
isabetli ad kalıbını yakalar. Hem üretim anında (``root_cause_service.
_validate_and_normalise``) hem eski kayıtların geri doldurmasında
(``scripts/mask_root_cause_payloads.py``) kullanılır; idempotenttir.

Bilinçli SINIR: genel "büyük harfle başlayan iki kelime" kuralı YOK —
"Kargo Firması", "United States" gibi yanlış pozitifler alıntıyı
anlamsızlaştırır. Kargo takip numaraları (10-13 hane) telefon kalıbına
girmesin diye telefon kalıbı 0 / +90 / +CC öneki ister; TCKN yalnız
sağlama toplamı tutuyorsa maskelenir.
"""

from __future__ import annotations

import re

NAME_PLACEHOLDER = "[ad]"
EMAIL_PLACEHOLDER = "[e-posta]"
PHONE_PLACEHOLDER = "[telefon]"
ID_PLACEHOLDER = "[kimlik no]"
IBAN_PLACEHOLDER = "[iban]"

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# TR: +90 5xx xxx xx xx / 0 5xx ... / 0212 ... (10 hane + zorunlu önek).
_TR_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+\s?90|00\s?90|0)[\s.-]?\(?[1-9]\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)"
)
# Uluslararası: +CC ... (en az 9 hane, ayraçlı ya da bitişik).
_INTL_PHONE_RE = re.compile(
    r"(?<![\w+])\+\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{2,4}(?:[\s.-]?\d{2,4})?(?!\d)"
)
_IBAN_RE = re.compile(r"\bTR\d{2}(?:[\s-]?\d{4}){5}[\s-]?\d{2}\b", re.IGNORECASE)
_ELEVEN_DIGITS_RE = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")

_TR_UPPER = "A-ZÇĞİÖŞÜ"
_TR_WORD = rf"[{_TR_UPPER}][\wçğıöşüÇĞİÖŞÜ'’-]*"
# "Sayın Ayşe Yılmaz" / "Sn. Mehmet K." — hitap sonrası 1-3 büyük harfli
# kelime; genel hitaplar ("Sayın Müşterimiz") stoplist ile korunur.
_SALUTATION_RE = re.compile(
    rf"\b(Sayın|Sn\.?|Dear|Hello|Hi)\s+({_TR_WORD}(?:\s+{_TR_WORD}){{0,2}})(?=[\s,.;:!?)]|$)"
)
_SALUTATION_STOP = {
    "müşterimiz",
    "müşteri",
    "yetkili",
    "yetkililer",
    "ilgili",
    "ilgililer",
    "kullanıcı",
    "kullanıcımız",
    "bay",
    "bayan",
    "customer",
    "customers",
    "team",
    "support",
    "sir",
    "madam",
    "all",
    "destek",
    "ekibi",
    "ekip",
}
# İmza: "Saygılarımla, Ayşe Yılmaz" / "Best regards, John Doe".
_SIGNATURE_RE = re.compile(
    rf"\b(Saygılarımla|Saygılarımızla|Saygılar|İyi çalışmalar|Kolay gelsin|"
    rf"Best regards|Kind regards|Regards|Sincerely|Thanks|Thank you)\s*[,.]?\s+"
    rf"({_TR_WORD}(?:\s+{_TR_WORD}){{0,2}})(?=[\s,.;:!?)]|$)"
)
# Kargo bildirim şablonu: "sent by UYGAR CAMLIBEL to ALLY BEERS".
_SENT_BY_RE = re.compile(
    r"\b((?i:sent by|gönderen:|gönderici:|alıcı:|receiver:|recipient:))\s+"
    rf"({_TR_WORD}(?:\s+{_TR_WORD}){{0,3}})"
    r"(?=\s+(?:to|in|for|on|at)\b|[\s,.;:!?)]|$)"
)
_SENT_TO_RE = re.compile(
    rf"(\bsent by \[ad\] to\s+)({_TR_WORD}(?:\s+{_TR_WORD}){{0,3}})(?=\s+(?:in|for|on|at)\b|[\s,.;:!?)]|$)"
)


def _tckn_valid(digits: str) -> bool:
    d = [int(c) for c in digits]
    odd = d[0] + d[2] + d[4] + d[6] + d[8]
    even = d[1] + d[3] + d[5] + d[7]
    return (odd * 7 - even) % 10 == d[9] and sum(d[:10]) % 10 == d[10]


def _mask_tckn(match: re.Match[str]) -> str:
    digits = match.group(0)
    return ID_PLACEHOLDER if _tckn_valid(digits) else digits


def _mask_named(match: re.Match[str]) -> str:
    lead, name = match.group(1), match.group(2)
    first = name.split()[0].rstrip(".,").lower()
    if first in _SALUTATION_STOP:
        return match.group(0)
    return f"{lead} {NAME_PLACEHOLDER}"


def mask_pii(text: str) -> str:
    """E-posta, telefon, TCKN, IBAN ve yüksek isabetli ad kalıplarını yer
    tutucuyla değiştirir. Yer tutucular sabit Türkçe ("[ad]" vb.); web
    tarafı yerelleştirir. İdempotent — maskeli metin değişmeden döner."""
    if not text:
        return text
    out = _EMAIL_RE.sub(EMAIL_PLACEHOLDER, text)
    out = _IBAN_RE.sub(IBAN_PLACEHOLDER, out)
    out = _TR_PHONE_RE.sub(PHONE_PLACEHOLDER, out)
    out = _INTL_PHONE_RE.sub(PHONE_PLACEHOLDER, out)
    out = _ELEVEN_DIGITS_RE.sub(_mask_tckn, out)
    out = _SALUTATION_RE.sub(_mask_named, out)
    out = _SIGNATURE_RE.sub(_mask_named, out)
    out = _SENT_BY_RE.sub(_mask_named, out)
    out = _SENT_TO_RE.sub(lambda m: f"{m.group(1)}{NAME_PLACEHOLDER}", out)
    return out


def mask_pii_list(items: list[str]) -> list[str]:
    return [mask_pii(item) for item in items]
