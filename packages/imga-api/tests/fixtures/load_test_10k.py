"""Sprint 9.1 G — synthetic 10K Turkish-comment fixture.

Generates a CSV with two columns (``text`` + ``nps_score``) and 10,000
rows for the production benchmark in
``tests/test_10k_benchmark.py``. The text bank is hand-curated short
phrases that exercise:

  * Positive / neutral / negative sentiment buckets
  * The category keywords the ``KeywordCategoryClassifier`` is tuned
    for (``kargo``, ``iade``, ``site``, ``ürün``, ``fiyat``, etc.)
  * Empty / whitespace-only rows (the parser must skip these without
    burning BERT inference)

The fixture is deterministic — ``seed=20260509`` — so an apples-to-
apples re-run after a code change can compare timing 1:1.

Usage:

    from tests.fixtures.load_test_10k import generate_10k_csv
    csv_path = generate_10k_csv(tmp_path / "10k.csv")

The generator is fast (<200 ms) so it lands inline in test setup
rather than committing a 1 MB CSV.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

# Hand-curated Turkish customer-review phrasings, grouped roughly by
# the sentiment label the BERT model usually returns. The mix is
# intentionally weighted toward negative + neutral because the demo
# tenants over-index there (real customer-feedback distribution).
_POSITIVE_PHRASES: tuple[str, ...] = (
    "ürün gerçekten çok güzel teşekkürler",
    "kargo çok hızlı geldi memnunum",
    "site arayüzü çok kullanışlı tebrikler",
    "fiyat performansı süper",
    "iade süreci hiç sorunsuzdu çok iyi",
    "müşteri hizmetleri çok ilgili",
    "güzel paketleme dikkatli kargo",
    "tam beklediğim gibi geldi",
    "harika bir alışveriş tecrübesi",
    "kaliteli bir ürün tavsiye ederim",
)

_NEUTRAL_PHRASES: tuple[str, ...] = (
    "sipariş geldi inceliyorum",
    "fatura geldi mi acaba",
    "kargo henüz çıkmamış",
    "stoklarda var mı bilgi alabilir miyim",
    "ürünü iade etmek istiyorum",
    "hesabıma giriş yapamıyorum",
    "kargo takip numarası nedir",
    "telefon değişikliği yapacağım",
    "ürün özellikleri tam olarak ne",
    "nasıl sipariş verebilirim",
)

_NEGATIVE_PHRASES: tuple[str, ...] = (
    "kargo geç geldi çok kötü",
    "ürün hatalı çıktı iade istiyorum",
    "iade süreci berbat",
    "müşteri hizmetlerine ulaşamıyorum",
    "site sürekli hata veriyor",
    "fiyat etiketi yanıltıcı",
    "paketleme çok kötüydü kırık geldi",
    "ürün resimle uyuşmuyor",
    "ödememi geri alamıyorum",
    "çok kalitesiz bir ürün",
    "tekrar alışveriş yapmam",
    "kargo firması ile sorun yaşıyorum",
    "soğuk muamele berbat",
    "iade kargosu için para istediler kabul edilemez",
    "bekleme süresi haftaları geçti",
)

# Empty / whitespace markers — the worker must filter these without
# burning BERT inference. Mixed in at a 1% rate matching real upload
# noise.
_EMPTY_TOKEN = ""

DEFAULT_TOTAL_ROWS = 10_000
DEFAULT_SEED = 20260509  # ISO-y/m/d


def generate_10k_csv(
    output_path: Path,
    *,
    total_rows: int = DEFAULT_TOTAL_ROWS,
    seed: int = DEFAULT_SEED,
    include_empty_rate: float = 0.01,
) -> Path:
    """Write a deterministic 10K-row CSV. Returns the same path for
    convenience (so a test can do ``csv = generate_10k_csv(tmp / 'x')``
    inline)."""
    if total_rows <= 0:
        raise ValueError("total_rows must be > 0")
    rng = random.Random(seed)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["text", "nps_score"])
        for _ in range(total_rows):
            roll = rng.random()
            if roll < include_empty_rate:
                phrase = _EMPTY_TOKEN
            elif roll < 0.30:
                phrase = rng.choice(_POSITIVE_PHRASES)
            elif roll < 0.55:
                phrase = rng.choice(_NEUTRAL_PHRASES)
            else:
                phrase = rng.choice(_NEGATIVE_PHRASES)

            # NPS distribution skews toward extremes (the real-world
            # 0/10-heavy bimodal). 5-9 promoters; 0-3 detractors;
            # 4-6 the "passive" middle that AnalyticsService.compute_
            # nps_summary buckets as neither.
            nps_roll = rng.random()
            if nps_roll < 0.45:
                nps_score = rng.randint(7, 10)
            elif nps_roll < 0.65:
                nps_score = rng.randint(4, 6)
            else:
                nps_score = rng.randint(0, 3)
            writer.writerow([phrase, nps_score])
    return output_path


__all__ = [
    "DEFAULT_SEED",
    "DEFAULT_TOTAL_ROWS",
    "generate_10k_csv",
]
