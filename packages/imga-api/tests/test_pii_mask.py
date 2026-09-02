"""KVKK maskesi — services/pii_mask.py (2026-09-02).

Saf birim testleri; DB yok. Yanlış pozitif sınırları da test edilir:
kargo takip numarası, doğrulama kodu ve genel hitaplar ("Sayın
Müşterimiz") DOKUNULMAZ — alıntı anlamını kaybetmesin.
"""

from __future__ import annotations

import pytest

from imga_api.services.pii_mask import mask_pii, mask_pii_list


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mail: ayse.yilmaz@example.com adresine yazın", "mail: [e-posta] adresine yazın"),
        ("Bana 0532 123 45 67 ulaşın", "Bana [telefon] ulaşın"),
        ("+90 (212) 555 44 33 numarası", "[telefon] numarası"),
        ("05074229896 geri aramanızı bekliyor.", "[telefon] geri aramanızı bekliyor."),
        ("call +1 415 555 0132 today", "call [telefon] today"),
        ("IBAN TR33 0006 1005 1978 6457 8413 26", "IBAN [iban]"),
        ("Kimlik 10000000146 ile giriş", "Kimlik [kimlik no] ile giriş"),
        ("Sayın Ayşe Yılmaz, gönderiniz yola çıktı", "Sayın [ad], gönderiniz yola çıktı"),
        ("Saygılarımla, Mehmet Kaya. Teşekkürler", "Saygılarımla [ad]. Teşekkürler"),
        ("Best regards, John Doe", "Best regards [ad]"),
        (
            "Your shipment was sent by UYGAR CAMLIBEL to ALLY BEERS. In order for customs",
            "Your shipment was sent by [ad] to [ad]. In order for customs",
        ),
        ("Gönderici: Ali Veli teslim etti", "Gönderici: [ad] teslim etti"),
    ],
)
def test_masks_personal_data(raw: str, expected: str) -> None:
    assert mask_pii(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "Tracking ID: 875006773003 Your shipment is moving",  # 12 hane, telefon değil
        "sipariş 12345678901 iptal",  # 11 hane ama TCKN sağlaması tutmuyor
        "1Z9A77916732900054 ve 873289676432 numaralı gönderiler",
        "verification code is: 7801",
        "Sayın Müşterimiz, 19.06.2026 Cuma günü",
        "Değerli Müşterimiz, teşekkürler",
        "Hello Destek Destek, Your FedEx Support Hub",
        "Kargo Firması ile United States arasında",
        "Zaman:2026-07-11 09:59:07",
    ],
)
def test_leaves_non_personal_text_alone(raw: str) -> None:
    assert mask_pii(raw) == raw


def test_idempotent_on_masked_text() -> None:
    once = mask_pii("Sayın Ayşe Yılmaz, 0532 123 45 67, ayse@example.com")
    assert once == "Sayın [ad], [telefon], [e-posta]"
    assert mask_pii(once) == once


def test_empty_and_list() -> None:
    assert mask_pii("") == ""
    assert mask_pii_list(["a@b.co", "temiz"]) == ["[e-posta]", "temiz"]
