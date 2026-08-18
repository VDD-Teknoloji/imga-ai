"""Unit coverage for imga_api.services.data_quality.classify_data_quality.

No DB, no async — pure-function heuristic. 2026-08-18 "büyük paket" WS2:
this module is the ONLY source of 'informational' / 'meaningless'
``reviews.quality_flag`` values (the LLM prompt's "q" field attempt was
measured and rejected — see docs/analysis/2026-08-18-buyuk-paket-plan.md).

PRECISION IS THE CONTRACT UNDER TEST: a false positive here hides a
real complaint from analytics (WS2 default ``include_flagged=False``).

2026-08-18 adversarial review — SECOND pass. Empirically confirmed
false positives from the first design forced a rewrite of the module
AND this file:

  * the old "<=2 meaningful words" meaningless rule flagged real short
    reviews ('Beğenmedim', 'Hızlı kargo', 'kargo gecikmesi') — REMOVED
    entirely, not rescued with a bigger veto word list (inflected
    Turkish never closes that list).
  * the old shipping-status-phrase-alone informational trigger flagged
    real complaints that happen to quote the tracking message back
    ('Teslim edildi yazıyor, kutu boş çıktı') — informational now
    REQUIRES a template/automation marker; a shipping-status phrase by
    itself is no longer a trigger at all.

Every "must stay None" case below is a scenario the heuristic is NOT
allowed to flag, even though it superficially resembles the positive
pattern.
"""

from __future__ import annotations

import pytest

from imga_api.services.data_quality import classify_data_quality

# ---------------------------------------------------------------------------
# informational — should fire (template/automation marker + no
# first-person complaint stem).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Değerli müşterimiz, siparişiniz kargoya verildi. "
        "Takip numaranız: 482910.",
        "Sayın müşterimiz, hesabınıza ait doğrulama kodu: 837261. "
        "Bu kodu kimseyle paylaşmayınız.",
        "Bu e-posta otomatik olarak gönderilmiştir, lütfen "
        "yanıtlamayınız. Haftalık özet raporunuz hazır. "
        "Happy number crunching!",
        "Değerli müşterimiz, gönderiniz dağıtıma çıktı, bugün "
        "elinize ulaşacaktır.",
        "Sayın müşterimiz, siparişiniz kargoya verildi, takip "
        "numaranız 482910.",
    ],
)
def test_informational_patterns_are_flagged(text: str) -> None:
    assert classify_data_quality(text) == "informational"


# ---------------------------------------------------------------------------
# informational — must NEVER fire without a template/automation
# marker. A bare shipping-status sentence is no longer a trigger on
# its own (2026-08-18 redesign — this was the FP source for real
# complaints that quote the notification text back).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Teslim edildi yazıyor, kutu boş çıktı.",
        "Teslim edildi gözüküyor, paketim elimde yok.",
        "Kargoya verildi deniyor, 5 gündür bekliyorum.",
        # No marker at all, plain shipping-status wording alone.
        "Siparişiniz kargoya verildi, takip numaranız 482910.",
        "Gönderiniz dağıtıma çıktı, bugün elinize ulaşacaktır.",
    ],
)
def test_bare_shipping_status_is_never_informational(text: str) -> None:
    assert classify_data_quality(text) is None


# ---------------------------------------------------------------------------
# meaningless — should fire. One case per structural bucket the
# redesigned heuristic recognizes (see module docstring a-d).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # (a) no letters at all.
        "12345",
        "+90 555 123 45 67",
        "...",
        # (b) order/tracking-number label + digits, alone.
        "Sipariş no: 482910",
        "Tel: 0555 123 45 67",
        # (b) URL alone.
        "www.ornek-magaza.com",
        # (c) single token, greeting/filler whitelist.
        "Tamam",
        "Merhaba",
        "Test",
        # (d) single token, 4+ letters, zero Turkish vowels
        # (keyboard mash — no real Turkish word can be vowel-free).
        "qwrty",
        "sdfgh",
    ],
)
def test_meaningless_patterns_are_flagged(text: str) -> None:
    assert classify_data_quality(text) == "meaningless"


# ---------------------------------------------------------------------------
# meaningless — the empirically confirmed false positives. All of
# these are real 2-3 word reviews the OLD "<=2 meaningful words" rule
# wrongly flagged. The rule is gone; these must all be None now.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Beğenmedim",
        "Beğendim",
        "Hızlı kargo",
        "Yavaş kargo",
        "çok pahalı",
        "Kargom nerede",
        "Ürün kaliteli",
        "ses gelmiyor",
        "kargo gecikmesi",
        "bayıldım",
        "kesinlikle alın",
        "eline sağlık",
    ],
)
def test_confirmed_false_positives_are_never_flagged(text: str) -> None:
    assert classify_data_quality(text) is None


# ---------------------------------------------------------------------------
# Short-but-real sentiment must NEVER be flagged meaningless — length
# alone is not a signal in the redesigned heuristic.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "çok kötü",
        "berbat",
        "rezalet",
        "iyi",
        "güzel değil",
        "mükemmel",
        "yok",
    ],
)
def test_short_real_sentiment_is_never_meaningless(text: str) -> None:
    assert classify_data_quality(text) is None


# ---------------------------------------------------------------------------
# Polite complaints must NEVER be classified as informational, even
# when they open with a formal greeting or mention a shipping-status
# phrase that also appears in a template message.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Değerli yetkili, siparişim geldi ama içindeki ürün "
        "hasarlıydı, ne yapmam gerekiyor acaba?",
        "Merhabalar, kargom bugün teslim edildi yazıyor fakat elime "
        "hiçbir şey ulaşmadı. Yardımcı olabilir misiniz?",
        "Rica etsem kargomun nerede olduğunu öğrenebilir miyim, "
        "hâlâ elime geçmedi.",
        "Sayın müşteri hizmetleri, gönderim yola çıktı bildirimi "
        "geldi ama üç gündür hiçbir hareket yok, çok mağdur oldum.",
        "Bu ürünle ilgili ciddi bir şikayetim var, lütfen dönüş "
        "yapar mısınız?",
        # Template marker present, but a first-person complaint stem
        # vetoes it — the required "marker AND no-complaint" gate.
        "Değerli müşterimiz diye başlıyor ama paketim hâlâ yok, "
        "bu nasıl bir hizmet anlayışı?",
    ],
)
def test_polite_complaints_are_never_informational(text: str) -> None:
    assert classify_data_quality(text) is None


def test_informational_marker_without_complaint_wins() -> None:
    """Sanity check for the veto's precision: the SAME closing line
    ('teşekkürler') around a genuine template marker does not save a
    review from being informational when there is no complaint stem —
    'teşekkürler' carries no special meaning any more (the old global
    veto-word system that made it a rescue word is gone)."""
    assert (
        classify_data_quality(
            "Değerli müşterimiz, siparişiniz kargoya verildi. "
            "Bizi tercih ettiğiniz için teşekkürler."
        )
        == "informational"
    )


# ---------------------------------------------------------------------------
# Normal, substantive reviews (positive or negative) must stay None
# regardless of length — the default "valid row" case. Two-three word
# reviews are explicitly included: length is no longer a signal.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Sipariş verdiğim ürün 10 gündür kargoda bekliyor, müşteri "
        "hizmetlerini aradım ama kimse net bilgi veremedi.",
        "Ürün tam istediğim gibi geldi, paketleme özenliydi, "
        "teşekkür ederim.",
        "Fiyatı biraz yüksek buldum ama kalitesi bu fiyatı hak ediyor.",
        "İade sürecim iki haftadır sonuçlanmadı, paramı geri istiyorum.",
        "Deneme test",  # 2 low-content words, still not meaningless.
    ],
)
def test_normal_reviews_are_never_flagged(text: str) -> None:
    assert classify_data_quality(text) is None


# ---------------------------------------------------------------------------
# Order/phone label pattern must NOT fire when real content
# accompanies the label — only a bare label+digits combination counts.
# ---------------------------------------------------------------------------


def test_order_label_with_real_complaint_is_not_meaningless() -> None:
    assert (
        classify_data_quality("Sipariş no 482910 hâlâ gelmedi, çok mağdurum")
        is None
    )


# ---------------------------------------------------------------------------
# Empty / whitespace-only text — this function is never the source of
# truth for the empty-text quality flag (the batch worker handles that
# via a separate write path before classify_data_quality is ever
# called), but the function must not raise on it and must return None.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_text_returns_none(text: str) -> None:
    assert classify_data_quality(text) is None


# ---------------------------------------------------------------------------
# Turkish-casing robustness — normalize_turkish's İ/I fold must not
# break either the marker matcher, the complaint-stem veto, or the
# meaningless bucket checks.
# ---------------------------------------------------------------------------


def test_uppercase_turkish_informational_still_matches() -> None:
    assert (
        classify_data_quality(
            "DEĞERLİ MÜŞTERİMİZ, SİPARİŞİNİZ KARGOYA VERİLDİ."
        )
        == "informational"
    )


def test_uppercase_turkish_complaint_veto_still_blocks() -> None:
    assert (
        classify_data_quality(
            "DEĞERLİ MÜŞTERİMİZ, KARGOM HÂLÂ GELMİYOR."
        )
        is None
    )


def test_uppercase_turkish_meaningless_still_matches() -> None:
    assert classify_data_quality("TAMAM") == "meaningless"
