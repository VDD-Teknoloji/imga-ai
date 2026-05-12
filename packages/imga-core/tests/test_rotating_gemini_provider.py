"""Sprint 9.0.5-A R5 — RotatingGeminiProvider + classifier rotation
integration coverage.

The provider wraps the existing ``GeminiKeyRotator`` (Sprint 8.3.6
priority walk + RateLimit/InvalidKey fall-through) around per-call
ephemeral ``GeminiProvider`` instances so the classifier batch path
gains multi-key rotation without duplicating the rotator's logic.

These tests stub out the underlying ``GeminiProvider`` (so we don't
hit a real Gemini SDK / network) and pin:

  * Single-key tenants still work (trivial rotation, primary always
    chosen).
  * Rate-limited primary falls through to the next priority.
  * Invalid primary key falls through (separate error class, same
    rotator behaviour).
  * Every key exhausted -> AllKeysExhaustedError mapped to
    LLMProviderError so the HybridClassifier batch path counts it
    toward the circuit-breaker counter.
  * Non-rotator errors (MalformedResponseError, generic
    LLMProviderError without rate-limit hints) propagate unchanged.
  * AnalysisPipeline.analyze_batch_async accepts a ``classifier``
    override (R5 worker-injection contract).

Stubbing strategy: monkey-patch
``imga_core.llm.rotating_gemini.GeminiProvider`` to a lambda that
records the api_key + raises configured errors. Each test owns its
own stub; no global state.
"""

from __future__ import annotations

import asyncio

import pytest
from imga_core.llm import RotatingGeminiProvider
from imga_core.llm.base import LLMProviderError
from imga_core.llm.errors import RateLimitError
from imga_core.llm.key_rotation import GeminiKey
from imga_core.models import LLMClassificationResult


def _make_keys(*aliases: str) -> list[GeminiKey]:
    return [
        GeminiKey(
            id=f"id-{a}", value=f"key-{a}", label=a, priority=i
        )
        for i, a in enumerate(aliases)
    ]


def _result(primary: str = "ok") -> LLMClassificationResult:
    return LLMClassificationResult(
        primary=primary,
        confidence=0.9,
        reasoning="stub",
        provider="gemini",
        model="gemini-2.5-flash",
    )


class _StubProvider:
    """Fake ``GeminiProvider`` recording the api_key it was built
    with. Tests configure its ``classify`` behaviour via class-level
    knobs that the test mutates between runs."""

    behaviours: dict[str, Exception | LLMClassificationResult] = {}
    constructions: list[str] = []

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash", **_kw: object) -> None:
        self._key = api_key
        self.constructions.append(api_key)

    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        outcome = self.behaviours.get(self._key)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, LLMClassificationResult):
            return outcome
        return _result()

    def health_check(self) -> bool:
        return True


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> type[_StubProvider]:
    """Replace GeminiProvider with a recording stub. Reset class
    state so each test starts clean."""
    _StubProvider.behaviours = {}
    _StubProvider.constructions = []
    monkeypatch.setattr(
        "imga_core.llm.rotating_gemini.GeminiProvider", _StubProvider
    )
    return _StubProvider


# --- single-key smoke -------------------------------------------------


@pytest.mark.asyncio
async def test_single_key_classify_async_uses_only_key(
    stub_provider: type[_StubProvider],
) -> None:
    keys = _make_keys("solo")
    rp = RotatingGeminiProvider(keys=keys)
    result = await rp.classify_async("text", ["a", "b"])
    assert result.primary == "ok"
    # Exactly one ephemeral GeminiProvider built, with the only key.
    assert stub_provider.constructions == ["key-solo"]


# --- rotator fall-through --------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_falls_through_to_next_priority(
    stub_provider: type[_StubProvider],
) -> None:
    keys = _make_keys("primary", "fallback")
    stub_provider.behaviours = {
        "key-primary": RateLimitError(),
        "key-fallback": _result("from-fallback"),
    }
    rp = RotatingGeminiProvider(keys=keys)
    result = await rp.classify_async("text", ["a"])
    assert result.primary == "from-fallback"
    # Primary tried first, fall-through to fallback.
    assert stub_provider.constructions == ["key-primary", "key-fallback"]


@pytest.mark.asyncio
async def test_invalid_key_falls_through_via_message_sniff(
    stub_provider: type[_StubProvider],
) -> None:
    """Legacy path: GeminiProvider.classify raises LLMProviderError
    when the SDK rejects a 401/403 response. The provider's
    ``_maybe_rotate`` helper sniffs the message and re-raises as
    InvalidKeyError so the rotator falls through. This catches a
    regression in that mapping."""
    keys = _make_keys("dead", "alive")
    stub_provider.behaviours = {
        "key-dead": LLMProviderError("API key not valid"),
        "key-alive": _result("from-alive"),
    }
    rp = RotatingGeminiProvider(keys=keys)
    result = await rp.classify_async("text", ["a"])
    assert result.primary == "from-alive"
    assert stub_provider.constructions == ["key-dead", "key-alive"]


# --- exhaustion + non-rotator errors ---------------------------------


@pytest.mark.asyncio
async def test_all_keys_exhausted_raises_llm_provider_error(
    stub_provider: type[_StubProvider],
) -> None:
    """Every key returns rate-limit -> AllKeysExhaustedError ->
    re-raised as LLMProviderError so HybridClassifier counts it
    toward the circuit-breaker counter."""
    keys = _make_keys("k1", "k2")
    stub_provider.behaviours = {
        "key-k1": RateLimitError(),
        "key-k2": RateLimitError(),
    }
    rp = RotatingGeminiProvider(keys=keys)
    with pytest.raises(LLMProviderError, match="exhausted"):
        await rp.classify_async("text", ["a"])
    # Both keys attempted before giving up.
    assert stub_provider.constructions == ["key-k1", "key-k2"]


@pytest.mark.asyncio
async def test_provider_error_falls_through_to_fallback_key(
    stub_provider: type[_StubProvider],
) -> None:
    """Sprint 9.4.3 B — LLMProviderError (504 / 500 / network) used
    to propagate without rotation on the R7 rationale that a
    server-side outage is independent of the key. The 9.4.3 demo
    observation flipped this: with a primary that 504s and a
    fallback key that holds, the operator's "second key never gets
    tried" complaint is real. LLMProviderError now triggers
    rotation; the previous-behaviour assertion (only-primary-tried)
    is replaced with the new contract (fallback succeeds when
    primary errors)."""
    keys = _make_keys("k1", "k2")
    stub_provider.behaviours = {
        "key-k1": LLMProviderError("Gemini API call failed: 500 internal"),
        "key-k2": _result("served-by-fallback"),
    }
    rp = RotatingGeminiProvider(keys=keys)
    result = await rp.classify_async("text", ["a"])
    assert result.primary == "served-by-fallback"
    # Both keys attempted — primary errored, fallback succeeded.
    assert stub_provider.constructions == ["key-k1", "key-k2"]


# --- empty key list rejected -----------------------------------------


def test_constructor_rejects_empty_keys() -> None:
    """Service layer should fall through to keyword-only when the
    tenant has no credentials; an empty list at the provider layer
    is a configuration bug, not a runtime state."""
    with pytest.raises(ValueError, match="at least one"):
        RotatingGeminiProvider(keys=[])


# --- LLMProvider.classify_async default ------------------------------


def test_llm_provider_classify_async_default_delegates_to_classify() -> None:
    """The base class's ``classify_async`` runs the sync ``classify``
    on a worker thread. This pins the backwards-compat property so
    legacy single-key providers (GeminiProvider) gain the async
    surface for free."""
    from imga_core.llm.base import LLMProvider

    class _FakeProvider(LLMProvider):
        def __init__(self) -> None:
            self.calls = 0

        def classify(
            self, text: str, available_categories: list[str]
        ) -> LLMClassificationResult:
            self.calls += 1
            return _result()

        def health_check(self) -> bool:
            return True

    fake = _FakeProvider()
    result = asyncio.run(fake.classify_async("t", ["a"]))
    assert result.primary == "ok"
    assert fake.calls == 1


# --- AnalysisPipeline classifier override ----------------------------


@pytest.mark.asyncio
async def test_pipeline_analyze_batch_async_uses_classifier_override() -> None:
    """The R5 worker injects a per-job tenant classifier into
    AnalysisPipeline.analyze_batch_async via the ``classifier`` kwarg.
    With override set, the pipeline's own ``self.classifier`` must
    be ignored for this call."""
    from imga_core import AnalysisPipeline, KeywordCategoryClassifier
    from imga_core.analyzers.base import AnalyzerPrediction, SentimentAnalyzer
    from imga_core.classifiers.base import CategoryClassifier
    from imga_core.config import LABEL_NEUTRAL
    from imga_core.models import CategoryClassification

    class _StubAnalyzer(SentimentAnalyzer):
        def analyze_batch(
            self, texts: list[str]
        ) -> list[AnalyzerPrediction]:
            return [
                AnalyzerPrediction(label=LABEL_NEUTRAL, score=0.0)
                for _ in texts
            ]

    class _RecordingClassifier(CategoryClassifier):
        def __init__(self, label: str) -> None:
            self.label = label
            self.batch_calls = 0

        def classify(self, text: str) -> CategoryClassification:
            return CategoryClassification(
                primary=self.label,
                primary_confidence=1.0,
                primary_matched_keywords=(),
                secondaries=(),
                method="keyword",
                requires_manual_review=False,
            )

        def classify_batch(
            self, texts: list[str]
        ) -> list[CategoryClassification]:
            self.batch_calls += 1
            return [self.classify(t) for t in texts]

    default_clf = _RecordingClassifier("default")
    override_clf = _RecordingClassifier("override")
    pipeline = AnalysisPipeline(
        analyzer=_StubAnalyzer(), classifier=default_clf,
    )

    results = await pipeline.analyze_batch_async(
        ["a", "b"], classifier=override_clf,
    )
    assert len(results) == 2
    assert all(
        r.categorization is not None and r.categorization.primary == "override"
        for r in results
    )
    assert default_clf.batch_calls == 0
    assert override_clf.batch_calls == 1

    # No override -> default takes over.
    _ = await pipeline.analyze_batch_async(["c"])
    assert default_clf.batch_calls == 1
