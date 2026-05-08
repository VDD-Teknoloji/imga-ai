"""Hybrid classifier: keyword first, LLM fallback when confidence is low.

Strategy:
    1. Run KeywordCategoryClassifier
    2. If primary_confidence >= threshold, return as-is (cheap path)
    3. Otherwise call the LLM provider; on success merge result
    4. If LLM fails or is None, return keyword result with the
       requires_manual_review flag so the operator can step in

Sprint 9.0.5-A R4 — added ``classify_batch_async`` with parallel
LLM dispatch + circuit breaker + per-batch telemetry. The legacy
sync ``classify_batch`` (default loop) ran 98 LLM fallbacks in
sequence — on a Gemini-bound demo tenant that was 161 sec wall-
clock for what should be ~15-25 sec. The async path bounds
parallel LLM calls by ``LLM_CONCURRENCY`` (default 8 — paid Tier
1 supplies ~16 RPS, so 8 in flight stays well under quota with
margin for the ~2 sec/call latency).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from imga_core.categories.taxonomy import GLOBAL_CATEGORY_CODES
from imga_core.classifiers.base import CategoryClassifier
from imga_core.classifiers.keyword import KeywordCategoryClassifier
from imga_core.config import CATEGORY_LLM_FALLBACK_THRESHOLD
from imga_core.llm.base import LLMProvider, LLMProviderError
from imga_core.models import CategoryClassification

if TYPE_CHECKING:
    pass

_logger = logging.getLogger(__name__)


# Sprint 9.0.5-A R4 — parallel LLM dispatch defaults.
#
# LLM_CONCURRENCY: max simultaneous Gemini calls per batch. Paid Tier 1
# is 1000 RPM ≈ 16 RPS; with ~2 sec/call latency, 8 in flight averages
# 4 RPS sustained — well under the ceiling and leaves headroom for
# burst, the SWOT/OKR path, and any other tenants sharing the key.
# Override per-instance (HybridClassifier(..., llm_concurrency=N)) when
# a deployment moves to a different tier.
# Sprint 9.0.5-A R7 → R7 follow-up: 8 → 4 → 8.
# R7 dropped 8 to 4 as a defensive measure during the 504-storm
# fix. py-spy Pattern A validation post-deploy confirmed the SDK
# retry-disable + asyncio safety net + mid-batch cancel are doing
# their job — fan-out goes back to 8 to recover the demo's
# throughput target without re-introducing the OOM regression.
# Paid Gemini Tier 1 is 1000 RPM ≈ 16 RPS; 8 in flight averages
# ~8 RPS sustained. Override per-instance via the
# ``llm_concurrency`` constructor arg or the BatchSettings
# ``llm_concurrency`` field on the worker.
DEFAULT_LLM_CONCURRENCY = 8

# Sprint 9.0.5-A R4 — circuit breaker — kicks in on N consecutive
# provider failures so a Gemini outage in the middle of a 10K-row
# batch doesn't burn through the rest of the rows on doomed retries.
#
# Sprint 9.0.5-A R7 — tightened thresholds after a 504-storm smoke
# test:
#  * threshold 5 -> 3: the older value let a hung batch keep firing
#    LLM calls long enough for in-flight tasks + SDK retry state to
#    grow memory from 252 MiB to 3+ GiB. Three failures is enough
#    signal of a real problem.
#  * cooldown 30s -> 60s: Gemini server outages typically last
#    multiple minutes; 30s reopened the circuit before the upstream
#    recovered and the batch immediately got stuck again.
CIRCUIT_BREAKER_FAIL_THRESHOLD = 3
CIRCUIT_BREAKER_COOLDOWN_SECONDS = 60.0


class HybridClassifier(CategoryClassifier):
    """Keyword + optional LLM fallback.

    Args:
        keyword_classifier: Required cheap-path classifier.
        llm_provider: Optional LLM provider. None means LLM fallback is
            disabled — low-confidence results go straight to manual review.
        confidence_threshold: Below this keyword confidence the LLM (if
            available) is consulted. Default 0.7 from config.
        available_categories: Codes the LLM is allowed to choose from. If
            None, defaults to the global taxonomy.
        llm_concurrency: Max parallel LLM calls in
            ``classify_batch_async``. Default 8 (see
            DEFAULT_LLM_CONCURRENCY rationale).
    """

    def __init__(
        self,
        keyword_classifier: KeywordCategoryClassifier,
        llm_provider: LLMProvider | None = None,
        confidence_threshold: float = CATEGORY_LLM_FALLBACK_THRESHOLD,
        available_categories: list[str] | None = None,
        llm_concurrency: int = DEFAULT_LLM_CONCURRENCY,
    ) -> None:
        self.keyword = keyword_classifier
        self.llm = llm_provider
        self.threshold = confidence_threshold
        self._available_categories = available_categories or list(GLOBAL_CATEGORY_CODES)
        self._llm_concurrency = max(1, llm_concurrency)
        # Sprint 9.0.5-A R6 — instance-level semaphore so all
        # classify_batch_async calls on the SAME classifier share
        # one cap. R5 created a fresh ``asyncio.Semaphore`` inside
        # every call, which meant each chunk got its own 8-cap and
        # the worker's 4-chunk parallel path could fan out 32
        # concurrent LLM requests — well beyond paid Tier 1's
        # comfortable burst window. With one classifier per job
        # (worker integration), this gives true job-level global
        # concurrency. Lazy init so the Semaphore binds to the
        # event loop the first batch runs on (test isolation +
        # production lifespan loop both work).
        self._llm_semaphore: asyncio.Semaphore | None = None
        # Sprint 9.0.5-A R4 — circuit-breaker state. Keep on the
        # instance so a fresh classifier per batch (test path) starts
        # closed; production keeps a long-lived classifier on the
        # WorkerContext, so failures + cooldowns persist across
        # batches as intended.
        self._consecutive_llm_failures = 0
        self._llm_circuit_open_until: float | None = None

    def _get_llm_semaphore(self) -> asyncio.Semaphore:
        """Sprint 9.0.5-A R6 — lazy-init so the Semaphore's loop
        binding picks up the first event loop the classifier is
        used on. Constructed once per instance; concurrent
        classify_batch_async calls reuse it, capping total in-
        flight LLM calls across the whole classifier lifetime."""
        if self._llm_semaphore is None:
            self._llm_semaphore = asyncio.Semaphore(self._llm_concurrency)
        return self._llm_semaphore

    def classify(self, text: str) -> CategoryClassification:
        keyword_result = self.keyword.classify(text)

        # Cheap path: keyword is confident enough.
        if keyword_result.primary_confidence >= self.threshold:
            return keyword_result

        # No LLM configured: surface for manual review.
        if self.llm is None:
            return keyword_result.model_copy(update={"requires_manual_review": True})

        # Skip LLM for empty / unclassifiable input — keyword classifier
        # already returned the fallback bucket and there's nothing for the
        # LLM to work with.
        if not text or not text.strip():
            return keyword_result.model_copy(update={"requires_manual_review": True})

        try:
            llm_result = self.llm.classify(text, self._available_categories)
        except LLMProviderError as exc:
            _logger.warning(
                "LLM classification failed (%s); falling back to keyword result", exc
            )
            return keyword_result.model_copy(update={"requires_manual_review": True})

        # Merge: LLM picks primary + confidence, keyword keeps secondaries.
        return _merge_with_llm(keyword_result, llm_result)

    # ------------------------------------------------------------------
    # Sprint 9.0.5-A R4 — async batch with parallel LLM fallback
    # ------------------------------------------------------------------

    async def classify_batch_async(
        self, texts: list[str]
    ) -> list[CategoryClassification]:
        """Async batch classification with bounded parallel LLM dispatch.

        Steps:
          1. Run keyword classify on every text (sync, microseconds — no
             network).
          2. Identify the indices whose keyword confidence is below
             threshold (LLM fallback candidates).
          3. Fan out the LLM calls through ``asyncio.to_thread`` bounded
             by ``self._llm_concurrency``. Failures don't fail the batch
             — the row falls back to keyword + ``requires_manual_review``,
             same contract as the sync ``classify``.
          4. Circuit breaker: ``CIRCUIT_BREAKER_FAIL_THRESHOLD`` (5)
             consecutive failures opens the circuit for
             ``CIRCUIT_BREAKER_COOLDOWN_SECONDS`` (30s); pending LLM
             calls (and any subsequent batch in the cooldown window)
             skip the LLM hop entirely so an outage doesn't burn the
             rest of a 10K-row run on doomed retries.
          5. Telemetry: one INFO log per batch with throughput +
             keyword/LLM split + duration so an operator can see the
             demo's classifier breakdown live in journalctl.

        Demo target: 98-row LLM-bound batch was 161 sec sequential
        (Sprint 9.0.5-A R4 incident); 8 in flight × 2 sec/call × 13
        batches ≈ 26 sec wall-clock + keyword overhead. ~6× faster
        without touching Gemini quota.
        """
        batch_started_at = time.monotonic()
        total = len(texts)

        # Step 1: keyword pass (sync, fast).
        keyword_results = [self.keyword.classify(t) for t in texts]

        # Step 2: identify LLM candidates.
        llm_candidates = [
            i
            for i, r in enumerate(keyword_results)
            if r.primary_confidence < self.threshold
            and texts[i] is not None
            and texts[i].strip()
        ]

        # Early-exit branches — no LLM work to dispatch.
        if not llm_candidates:
            self._log_batch_summary(
                total=total,
                llm_attempted=0,
                llm_success=0,
                duration_seconds=time.monotonic() - batch_started_at,
                mode="keyword-only",
                keys_stats=self._read_provider_stats(),
            )
            return _mark_review_for_low_confidence(
                keyword_results, self.threshold,
            )

        if self.llm is None:
            self._log_batch_summary(
                total=total,
                llm_attempted=0,
                llm_success=0,
                duration_seconds=time.monotonic() - batch_started_at,
                mode="llm-disabled",
                keys_stats=None,
            )
            return _mark_review_for_low_confidence(
                keyword_results, self.threshold,
            )

        if self._is_circuit_open():
            _logger.warning(
                "LLM circuit open — skipping %d LLM fallback calls "
                "(cooldown ends in %.1fs)",
                len(llm_candidates),
                self._cooldown_remaining_seconds(),
            )
            self._log_batch_summary(
                total=total,
                llm_attempted=0,
                llm_success=0,
                duration_seconds=time.monotonic() - batch_started_at,
                mode="circuit-open",
                keys_stats=self._read_provider_stats(),
            )
            return _mark_review_for_low_confidence(
                keyword_results, self.threshold,
            )

        # Step 3: fan out LLM calls bounded by concurrency.
        # Sprint 9.0.5-A R6 — instance-level semaphore so all batches
        # on this classifier share one cap (job-level global
        # concurrency on the worker). R5's per-call construction
        # gave each chunk its own 8-cap which compounded to 32 in
        # flight under 4-way chunk parallelism.
        semaphore = self._get_llm_semaphore()

        async def _llm_one(idx: int) -> tuple[int, CategoryClassification | None]:
            async with semaphore:
                # Re-check circuit after the wait — a flood of
                # failures from the first few in-flight calls may
                # have opened it while this task was queued.
                if self._is_circuit_open():
                    return idx, None
                try:
                    # Sprint 9.0.5-A R5 — call the provider's async
                    # surface so multi-key implementations
                    # (RotatingGeminiProvider) can use the async
                    # rotator natively. The default LLMProvider
                    # implementation routes back through
                    # ``asyncio.to_thread(self.classify, ...)`` so
                    # single-key providers behave the same as before.
                    llm_result = await self.llm.classify_async(  # type: ignore[union-attr]
                        texts[idx], self._available_categories,
                    )
                except LLMProviderError as exc:
                    self._record_llm_failure()
                    _logger.warning(
                        "LLM classification failed for row %d (%s); "
                        "falling back to keyword result",
                        idx,
                        exc,
                    )
                    return idx, None
                except Exception:
                    # Anything non-LLMProviderError still counts as a
                    # provider failure for the circuit-breaker purposes
                    # (a malformed-input crash from the provider SDK
                    # is just as much a signal as a network timeout).
                    self._record_llm_failure()
                    _logger.exception(
                        "Unexpected LLM error for row %d", idx
                    )
                    return idx, None
                self._record_llm_success()
                return idx, _merge_with_llm(
                    keyword_results[idx], llm_result,
                )

        # Sprint 9.0.5-A R7 — track tasks so the circuit breaker can
        # cancel pending work mid-batch. Earlier the gather() awaited
        # every task to completion even after the circuit opened, so
        # a 504 storm that tripped the breaker on row 3 still ran the
        # remaining 197 rows of a 200-row chunk against a doomed
        # provider before the batch summary line emitted. With
        # cancellation, the chunk surfaces partial-result with
        # manual_review on the cancelled rows immediately.
        pending: dict[asyncio.Task[tuple[int, CategoryClassification | None]], int] = {}
        for cand_idx in llm_candidates:
            task = asyncio.create_task(_llm_one(cand_idx))
            pending[task] = cand_idx

        llm_outcomes: list[tuple[int, CategoryClassification | None]] = []
        cancelled_indices: set[int] = set()

        while pending:
            done, _waiting = await asyncio.wait(
                pending.keys(), return_when=asyncio.FIRST_COMPLETED
            )
            for finished in done:
                cand_idx = pending.pop(finished)
                if finished.cancelled():
                    cancelled_indices.add(cand_idx)
                    continue
                exc = finished.exception()
                if exc is not None:
                    # _llm_one swallows expected provider errors and
                    # surfaces None; an exception escaping here is a
                    # bug or an unexpected error type. Treat as a
                    # provider failure for breaker accounting + log.
                    self._record_llm_failure()
                    _logger.exception(
                        "Unexpected error in _llm_one (idx %d)",
                        cand_idx,
                        exc_info=exc,
                    )
                    llm_outcomes.append((cand_idx, None))
                    continue
                llm_outcomes.append(finished.result())

            # Mid-batch breaker check. Newly opened circuit means
            # pending LLM tasks are rolling toward an upstream we
            # know is down — cancel them to free memory + wall-clock.
            if self._is_circuit_open() and pending:
                _logger.warning(
                    "LLM circuit opened mid-batch — cancelling %d "
                    "pending tasks",
                    len(pending),
                )
                for task in pending:
                    task.cancel()
                # Drain so the loop exits cleanly + thread-pool
                # futures release their references.
                drain_results = await asyncio.gather(
                    *pending.keys(), return_exceptions=True,
                )
                for (task, cand_idx), _outcome in zip(
                    list(pending.items()), drain_results, strict=False,
                ):
                    cancelled_indices.add(cand_idx)
                pending.clear()

        # Step 4: assemble final list.
        final = list(keyword_results)
        llm_success = 0
        for idx, merged in llm_outcomes:
            if merged is not None:
                final[idx] = merged
                llm_success += 1
            else:
                # LLM failed — surface for manual review.
                final[idx] = keyword_results[idx].model_copy(
                    update={"requires_manual_review": True},
                )
        for idx in cancelled_indices:
            # Cancelled (circuit open mid-batch) — same review fate
            # as a hard LLM failure.
            final[idx] = keyword_results[idx].model_copy(
                update={"requires_manual_review": True},
            )

        self._log_batch_summary(
            total=total,
            llm_attempted=len(llm_candidates),
            llm_success=llm_success,
            duration_seconds=time.monotonic() - batch_started_at,
            mode="hybrid-parallel",
            keys_stats=self._read_provider_stats(),
        )
        return final

    def _read_provider_stats(self) -> dict[str, int] | None:
        """Sprint 9.0.5-A R6 follow-up — pull cumulative key-usage
        telemetry from the LLM provider when it exposes it (today:
        RotatingGeminiProvider; future: any provider implementing
        ``get_batch_stats``). Returns None for providers that don't
        — the legacy single-key GeminiProvider stays mute and the
        log line drops the key fields gracefully."""
        if self.llm is None:
            return None
        getter = getattr(self.llm, "get_batch_stats", None)
        if getter is None:
            return None
        try:
            stats = getter()
        except Exception:
            _logger.exception(
                "HybridClassifier: failed to read provider batch stats"
            )
            return None
        if not isinstance(stats, dict):
            return None
        return stats

    # ------------------------------------------------------------------
    # Circuit breaker helpers
    # ------------------------------------------------------------------

    def _is_circuit_open(self) -> bool:
        """Return True while the circuit is in cooldown. Auto-closes
        once the cooldown window ends (resets the failure counter)."""
        if self._llm_circuit_open_until is None:
            return False
        if time.monotonic() >= self._llm_circuit_open_until:
            self._llm_circuit_open_until = None
            self._consecutive_llm_failures = 0
            _logger.info("LLM circuit breaker closed; retrying LLM fallback")
            return False
        return True

    def _cooldown_remaining_seconds(self) -> float:
        if self._llm_circuit_open_until is None:
            return 0.0
        return max(0.0, self._llm_circuit_open_until - time.monotonic())

    def _record_llm_failure(self) -> None:
        self._consecutive_llm_failures += 1
        if (
            self._consecutive_llm_failures
            >= CIRCUIT_BREAKER_FAIL_THRESHOLD
            and self._llm_circuit_open_until is None
        ):
            self._llm_circuit_open_until = (
                time.monotonic() + CIRCUIT_BREAKER_COOLDOWN_SECONDS
            )
            _logger.warning(
                "LLM circuit breaker OPEN for %.0fs after %d "
                "consecutive failures — falling back to keyword-only "
                "classification until cooldown ends",
                CIRCUIT_BREAKER_COOLDOWN_SECONDS,
                self._consecutive_llm_failures,
            )

    def _record_llm_success(self) -> None:
        self._consecutive_llm_failures = 0

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    @staticmethod
    def _log_batch_summary(
        *,
        total: int,
        llm_attempted: int,
        llm_success: int,
        duration_seconds: float,
        mode: str,
        keys_stats: dict[str, int] | None = None,
    ) -> None:
        keyword_ok = total - llm_attempted
        throughput = (total / duration_seconds) if duration_seconds > 0 else 0.0
        # Sprint 9.0.5-A R6 follow-up — fold provider key-usage stats
        # into the same log line so an operator tailing journalctl
        # during the demo sees rotator fan-out alongside the
        # batch-level breakdown. Empty / missing stats produce a
        # blank suffix (legacy single-key providers).
        keys_suffix = ""
        if keys_stats:
            keys_suffix = (
                f" keys_used={keys_stats.get('keys_used', 0)}"
                f"/{keys_stats.get('keys_total', 0)}"
                f" rate_limit_events={keys_stats.get('rate_limit_events', 0)}"
            )
        _logger.info(
            "HybridClassifier batch | total=%d keyword_ok=%d "
            "llm_attempted=%d llm_success=%d/%d "
            "duration=%.2fs throughput=%.1f rows/s mode=%s%s",
            total,
            keyword_ok,
            llm_attempted,
            llm_success,
            llm_attempted,
            duration_seconds,
            throughput,
            mode,
            keys_suffix,
        )


def _merge_with_llm(
    keyword_result: CategoryClassification,
    llm_result: object,
) -> CategoryClassification:
    """LLM picks primary + confidence; keyword keeps secondaries.
    Mirrors the merge in the legacy sync ``classify`` so async + sync
    batches produce identical outputs for the same input."""
    return CategoryClassification(
        primary=llm_result.primary,  # type: ignore[attr-defined]
        primary_confidence=llm_result.confidence,  # type: ignore[attr-defined]
        primary_matched_keywords=(),
        secondaries=keyword_result.secondaries,
        method="ensemble",
        requires_manual_review=False,
        llm_result=llm_result,  # type: ignore[arg-type]
    )


def _mark_review_for_low_confidence(
    results: list[CategoryClassification],
    threshold: float,
) -> list[CategoryClassification]:
    """Apply the ``requires_manual_review`` flag to every keyword
    result whose confidence sits below the threshold. Used on the
    early-exit branches of ``classify_batch_async`` (no LLM
    candidates / LLM disabled / circuit open) so the contract
    matches the row-level ``classify`` path."""
    return [
        (
            r.model_copy(update={"requires_manual_review": True})
            if r.primary_confidence < threshold
            else r
        )
        for r in results
    ]
