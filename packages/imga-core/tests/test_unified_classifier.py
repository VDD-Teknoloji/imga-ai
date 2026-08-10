"""Sprint 11.0 — GeminiUnifiedEngine + pipeline unified yolu testleri.

Ağ yok: motorun ``_generate_sync``'i monkeypatch'lenir. Kapsam:
  * alt-batch bölme + sıra korunumu + eksik index'in nötr/belirsiz
    ile doldurulması
  * few-shot örneklerinin prompt'a girmesi
  * SDK hata eşlemesi (429 → RateLimitError → rotasyon)
  * pipeline.analyze_batch_unified_async: pre-override (critical)
    LLM kararını ezer; kategori unified'dan akar
"""

from __future__ import annotations

import pytest

from imga_core.analyzers.base import SentimentAnalyzer
from imga_core.llm.base import LLMProviderError
from imga_core.llm.errors import InvalidKeyError, RateLimitError
from imga_core.llm.key_rotation import GeminiKey
from imga_core.llm.unified_classifier import (
    FewShotExample,
    GeminiUnifiedEngine,
    UnifiedPrediction,
    _build_prompt,
    _map_sdk_error,
)
from imga_core.pipeline import AnalysisPipeline


def _keys() -> list[GeminiKey]:
    return [GeminiKey(id="k1", value="secret-1", label="test-key", priority=1)]


def test_build_prompt_includes_few_shot_and_categories() -> None:
    prompt = _build_prompt(
        ["Kargo gecikti", "Harika ürün"],
        ["kargo", "urun_kalitesi", "belirsiz"],
        (
            FewShotExample(
                text="Paket 10 gündür yolda",
                sentiment_label="NEGATIF",
                category="kargo",
                reason="SLA aşımı",
            ),
        ),
    )
    assert "kargo, urun_kalitesi, belirsiz" in prompt
    assert "Paket 10 gündür yolda" in prompt
    assert "İNSAN DÜZELTMELERİ" in prompt
    assert "0: Kargo gecikti" in prompt
    assert "1: Harika ürün" in prompt


@pytest.mark.asyncio
async def test_engine_preserves_order_and_fills_missing(monkeypatch) -> None:
    engine = GeminiUnifiedEngine(
        _keys(), model_name="test-model", call_batch_size=2
    )

    def fake_generate(api_key, prompt, chunk, categories, stats, options=None):
        stats.calls += 1
        out = {}
        for i, text in enumerate(chunk):
            if "atla" in text:
                continue  # model bu index'i atladı
            negative = "kötü" in text
            out[i] = UnifiedPrediction(
                sentiment_label="NEGATIF" if negative else "POZITIF",
                sentiment_score=-0.8 if negative else 0.8,
                category="kargo",
                category_confidence=0.9,
            )
        if not out:
            out[0] = UnifiedPrediction(
                sentiment_label="NÖTR", sentiment_score=0.0,
                category="belirsiz", category_confidence=0.0,
            )
        return out

    monkeypatch.setattr(engine, "_generate_sync", fake_generate)

    texts = ["kötü bir deneyim", "harika", "atla beni", "kötü paket"]
    predictions, stats = await engine.classify_unified_batch_async(
        texts, available_categories=["kargo", "belirsiz"]
    )
    assert len(predictions) == 4
    assert predictions[0].sentiment_label == "NEGATIF"
    assert predictions[1].sentiment_label == "POZITIF"
    # Atlanan index nötr/belirsiz ile doldurulur — satır kaybı yok.
    assert predictions[2].sentiment_label == "NÖTR"
    assert predictions[2].category == "belirsiz"
    assert predictions[3].sentiment_label == "NEGATIF"
    assert stats.calls == 2  # 4 metin / batch 2


def test_map_sdk_error_vocabulary() -> None:
    assert isinstance(
        _map_sdk_error(Exception("429 RESOURCE_EXHAUSTED: quota")),
        RateLimitError,
    )
    assert isinstance(
        _map_sdk_error(Exception("API key not valid (401)")),
        InvalidKeyError,
    )
    assert isinstance(
        _map_sdk_error(Exception("503 internal hiccup")),
        LLMProviderError,
    )


class _StubUnifiedEngine:
    """Pipeline testi için sabit cevaplı motor."""

    model_name = "stub"

    async def classify_unified_batch_async(
        self, texts, *, available_categories, few_shot=(), perspective_options=None
    ):
        from imga_core.llm.unified_classifier import UnifiedBatchStats

        predictions = [
            UnifiedPrediction(
                sentiment_label="POZITIF",
                sentiment_score=0.9,
                category="urun_kalitesi",
                category_confidence=0.85,
                perspective_code="product_quality_material",
            )
            for _ in texts
        ]
        return predictions, UnifiedBatchStats(calls=1)


class _NeverCalledAnalyzer(SentimentAnalyzer):
    def analyze_batch(self, texts):  # pragma: no cover — çağrılmamalı
        raise AssertionError("unified yolda BERT çağrılmamalı")


@pytest.mark.asyncio
async def test_pipeline_unified_path_pre_override_wins() -> None:
    pipeline = AnalysisPipeline(analyzer=_NeverCalledAnalyzer())
    stats: dict[str, int] = {}
    results = await pipeline.analyze_batch_unified_async(
        # 'hırsızlık' critical-keyword override'ını tetikler — LLM'in
        # POZITIF kararını ezmeli.
        ["Bu resmen hırsızlık, paramı geri istiyorum", "Çok memnun kaldım"],
        engine=_StubUnifiedEngine(),  # type: ignore[arg-type]
        available_categories=["urun_kalitesi", "belirsiz"],
        stats_sink=stats,
    )
    assert len(results) == 2
    assert results[0].sentiment_label == "NEGATIF"
    assert any(
        hit.layer == "critical" for hit in results[0].overrides_applied
    )
    # Kategori her iki satırda da unified'dan akar.
    assert results[0].categorization is not None
    assert results[0].categorization.primary == "urun_kalitesi"
    assert results[1].sentiment_label == "POZITIF"
    assert stats["llm_calls"] == 1


# --- Sprint 13.1 — alt kategori (p) alanı --------------------------------


_OPTIONS = {
    "kargo": [
        ("shipment_not_arrived", "Kargom ulaşmadı"),
        ("address_change", "Teslimat adresini değiştirebilir miyim?"),
    ],
    "faturalama": [("invoice_request", "Fatura Talebi")],
}


def test_build_prompt_lists_subcategories_per_main_category() -> None:
    prompt = _build_prompt(
        ["Kargom gelmedi"],
        ["kargo", "faturalama", "belirsiz"],
        (),
        None,
        _OPTIONS,
    )
    assert "ALT KATEGORİ" in prompt
    assert "- kargo: shipment_not_arrived = Kargom ulaşmadı" in prompt
    assert "invoice_request = Fatura Talebi" in prompt
    # Alt kategorisi olmayan ana kategori satır AÇMAZ.
    assert "- belirsiz:" not in prompt


def _parse_with_raw(raw: str, options=None):
    """``_generate_sync``'i ham JSON üstünde koştur (ağ yok)."""
    engine = GeminiUnifiedEngine(_keys(), model_name="test-model")
    from imga_core.llm.unified_classifier import UnifiedBatchStats

    stats = UnifiedBatchStats()
    engine._generate_raw_gemini = lambda api_key, prompt, s: raw  # type: ignore[method-assign]
    return engine._generate_sync(
        "key", "prompt", ["metin"], ["kargo", "faturalama", "belirsiz"],
        stats, options,
    )


def test_parse_threads_valid_perspective_code() -> None:
    parsed = _parse_with_raw(
        '[{"i": 0, "s": "NEGATIF", "sc": -0.7, "c": "kargo", "cc": 0.9, '
        '"p": "shipment_not_arrived"}]',
        _OPTIONS,
    )
    assert parsed[0].perspective_code == "shipment_not_arrived"


def test_parse_missing_or_null_perspective_is_none() -> None:
    without = _parse_with_raw(
        '[{"i": 0, "s": "NEGATIF", "sc": -0.7, "c": "kargo", "cc": 0.9}]',
        _OPTIONS,
    )
    assert without[0].perspective_code is None

    explicit_null = _parse_with_raw(
        '[{"i": 0, "s": "NEGATIF", "sc": -0.7, "c": "kargo", "cc": 0.9, '
        '"p": null}]',
        _OPTIONS,
    )
    assert explicit_null[0].perspective_code is None


def test_parse_rejects_code_outside_selected_main_category() -> None:
    # invoice_request faturalama'ya ait; ana kategori kargo geldiği için
    # kabul edilmez — çağıran keyword sezgiseline düşer.
    cross = _parse_with_raw(
        '[{"i": 0, "s": "NEGATIF", "sc": -0.7, "c": "kargo", "cc": 0.9, '
        '"p": "invoice_request"}]',
        _OPTIONS,
    )
    assert cross[0].perspective_code is None

    unknown = _parse_with_raw(
        '[{"i": 0, "s": "NEGATIF", "sc": -0.7, "c": "kargo", "cc": 0.9, '
        '"p": "uydurma_kod"}]',
        _OPTIONS,
    )
    assert unknown[0].perspective_code is None

    # Hiç seçenek verilmemişse (kurum taksonomisi eşlenmemiş) her kod düşer.
    no_options = _parse_with_raw(
        '[{"i": 0, "s": "NEGATIF", "sc": -0.7, "c": "kargo", "cc": 0.9, '
        '"p": "shipment_not_arrived"}]',
        None,
    )
    assert no_options[0].perspective_code is None


@pytest.mark.asyncio
async def test_pipeline_fills_perspective_sink() -> None:
    pipeline = AnalysisPipeline(analyzer=_NeverCalledAnalyzer())
    sink: list[str | None] = []
    await pipeline.analyze_batch_unified_async(
        ["Kumaş çok ince", "Dikişler açıldı"],
        engine=_StubUnifiedEngine(),  # type: ignore[arg-type]
        available_categories=["urun_kalitesi", "belirsiz"],
        perspective_sink=sink,
    )
    assert sink == ["product_quality_material", "product_quality_material"]


# --- 2026-08-10: GLM citli-JSON vakasi (prod OOM zinciri) -----------------


def test_parse_accepts_markdown_fenced_json() -> None:
    """GLM 5.2 gecerli JSON'u ```json citiyle sariyordu; parse reddi
    her chunk'i BERT fallback'ine dusurup worker'i OOM'a goturdu.
    Citli govde artik kabul edilir."""
    parsed = _parse_with_raw(
        '```json\n[{"i": 0, "s": "NEGATIF", "sc": -0.7, "c": "kargo", '
        '"cc": 0.9, "p": "shipment_not_arrived"}]\n```',
        _OPTIONS,
    )
    assert parsed[0].sentiment_label == "NEGATIF"
    assert parsed[0].perspective_code == "shipment_not_arrived"


def test_parse_accepts_json_with_leading_prose() -> None:
    parsed = _parse_with_raw(
        'Iste sonuclar:\n[{"i": 0, "s": "POZITIF", "sc": 0.8, '
        '"c": "kargo", "cc": 0.9}]',
        _OPTIONS,
    )
    assert parsed[0].sentiment_label == "POZITIF"


def test_parse_still_rejects_garbage() -> None:
    import pytest

    from imga_core.llm.base import LLMProviderError

    with pytest.raises(LLMProviderError):
        _parse_with_raw("tamamen serbest metin, json yok", _OPTIONS)
