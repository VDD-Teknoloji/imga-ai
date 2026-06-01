"""Sprint 9.7 — public trial analysis (≤100-row demo) for imga.ai.

The imga.ai marketing site proxies email-verified visitors into this
service through ``POST /public/trial/analyze``. We re-use the full
SaaS pipeline (BERT + Gemini hybrid classifier) but write **nothing**
to the production data path: no Review row, no Ticket, no batch
job. The result is a small aggregated payload (sentiment
distribution, top categories, sample excerpts, NPS estimate) that
lives in ``trial_analyses`` for 24h — the idempotency window —
then GC sweeps it.

Two design calls worth pinning here:

  1. **Singleton trial tenant.** Migration 0030 seeds a tenant with
     uuid ``00000000-0000-0000-0000-000000000777`` and slug
     ``trial``. Every row in ``trial_analyses`` references it, the
     RLS policy on the table is keyed on it, and the bind that the
     route runs sets ``app.current_tenant_id`` to it. Code that
     needs the value should import ``TRIAL_TENANT_ID`` from this
     module — the well-known uuid is more durable than a slug-
     lookup and avoids a round-trip on every request.

  2. **Pipeline reuse, no Review writes.** We call
     ``pipeline.analyze_batch_async(texts)`` with the lifespan-built
     classifier (env-configured Gemini key for the trial tenant —
     same operator infrastructure as the SaaS, no parallel auth
     surface). The returned ``AnalysisResult`` list is held in
     memory, aggregated, then dropped. Nothing in the reviews /
     tickets / strategic_reports universe is touched.

KVKK posture: see migration 0030's docstring. tl;dr: only
aggregates + sampled excerpts survive the 24h idempotency window;
nothing personally identifiable beyond email lingers beyond that.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from imga_core import AnalysisPipeline
from imga_core.models import AnalysisResult
from imga_db.models import Category, TrialAnalysis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.workers.file_parser import (
    FileParseError,
    UnsupportedFormatError,
    iter_rows,
    peek_header,
)
from imga_core.text_utils import normalize_turkish

_logger = logging.getLogger(__name__)


# Sprint 9.7 — well-known trial tenant id. Mirrors the seed insert
# in migration 0030. Pinned here so the route + service don't pay a
# slug-lookup round-trip per request.
TRIAL_TENANT_ID = UUID("00000000-0000-0000-0000-000000000777")

# 24h idempotency window — duplicate calls for the same email get the
# cached payload back. Matches the GC TTL on the table.
TRIAL_IDEMPOTENCY_TTL = timedelta(hours=24)

# Max rows the service will analyse. The route enforces the same cap
# but the service double-checks because the file_parser may produce
# more rows than the upper-stream byte cap implies (long CSV with
# tiny rows).
TRIAL_ROW_CAP = 100

# Sample reviews: target this many in the response, spread across
# sentiment buckets so the operator sees a mix.
SAMPLE_REVIEW_COUNT = 5

# Top-categories cap surfaced in the response.
TOP_CATEGORIES_COUNT = 5


class TrialAnalysisError(Exception):
    """Service-level errors. Route maps these to 422 / 400."""


class TrialEmptyError(TrialAnalysisError):
    """The file parsed cleanly but contained zero non-empty rows."""


class TrialNoTextColumnError(TrialAnalysisError):
    """smart_parser couldn't identify a review-text column."""


class TrialRowCapError(TrialAnalysisError):
    """The file had more than TRIAL_ROW_CAP data rows."""


async def get_cached_analysis(
    session: AsyncSession, *, email: str
) -> TrialAnalysis | None:
    """Idempotency lookup. Returns the existing row if its TTL hasn't
    expired; the route serves the cached aggregate without re-running
    the pipeline. None means no row or an expired one — the caller
    is free to proceed with a fresh analysis.

    Caller must have ``app.current_tenant_id`` set to TRIAL_TENANT_ID
    on this session (RLS gates).
    """
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(TrialAnalysis)
            .where(TrialAnalysis.email == email.lower().strip())
            .where(TrialAnalysis.expires_at > now)
        )
    ).scalar_one_or_none()
    return row


async def gc_expired(session: AsyncSession) -> int:
    """Lazy garbage collection. Called at the start of every fresh
    analysis so the table self-cleans without a worker. Returns the
    number of rows deleted (mostly for the structured log line)."""
    now = datetime.now(UTC)
    result = await session.execute(
        delete(TrialAnalysis).where(TrialAnalysis.expires_at <= now)
    )
    return result.rowcount or 0


async def run_trial_analysis(
    session: AsyncSession,
    *,
    pipeline: AnalysisPipeline,
    file_path: Path,
    file_name: str,
    email: str,
    trial_user_id: UUID | None,
) -> TrialAnalysis:
    """End-to-end analysis path.

    1. smart_parser detects the review-text column.
    2. parse_file extracts texts (cap ≤TRIAL_ROW_CAP, raise on overflow).
    3. pipeline.analyze_batch_async runs BERT + Gemini.
    4. Aggregates (sentiment dist, top categories, sample reviews,
       NPS estimate) computed in-memory.
    5. Result INSERTed into trial_analyses with expires_at = now+24h.

    Returns the persisted row. Raises TrialAnalysisError sub-types
    that the route maps to HTTP 422 / 400.
    """
    started = time.monotonic()

    # Step 1: detect text column via smart_parser. The detector picks
    # the column with the strongest review-text signal; the trial
    # path doesn't ask the user to override (no UI), so we rely on
    # the heuristic. A weak signal still wins because the detector
    # reports the highest-confidence match per column.
    text_column = _detect_text_column(file_path)
    if text_column is None:
        raise TrialNoTextColumnError(
            "yorum metni içeren bir kolon tespit edilemedi; "
            "CSV/XLSX'te 'yorum' / 'comment' / 'review' başlıklı "
            "bir sütun bekleniyor"
        )

    # Step 2: parse all rows + extract texts. We refuse anything over
    # the cap (defense-in-depth; the route already validates).
    texts = _extract_texts(file_path, text_column=text_column)
    if not texts:
        raise TrialEmptyError(
            "dosyada analiz edilebilir yorum bulunamadı; "
            "boş satırlar veya başlıksız bir dosya olabilir"
        )
    if len(texts) > TRIAL_ROW_CAP:
        raise TrialRowCapError(
            f"deneme analizi en fazla {TRIAL_ROW_CAP} satır kabul "
            f"eder; dosyada {len(texts)} satır var"
        )

    # Step 3: run BERT + classifier on the full text list. The
    # pipeline's lifespan-built classifier handles Gemini fallback
    # via env-configured keys; no per-tenant key lookup needed for
    # the trial path (the trial tenant doesn't need to manage its
    # own keys).
    results = await pipeline.analyze_batch_async(texts)

    # Step 4: aggregate.
    payload = _build_response_payload(results)

    # Step 5: persist. The route already cleared any expired row +
    # checked for an idempotent hit, so a straight INSERT here is
    # safe. ``request_id`` defaults to a fresh uuid.
    now = datetime.now(UTC)
    row = TrialAnalysis(
        tenant_id=TRIAL_TENANT_ID,
        email=email.lower().strip(),
        request_id=uuid4(),
        file_name=file_name,
        total_rows=len(texts),
        sentiment_distribution=payload["sentiment_distribution"],
        top_categories=payload["top_categories"],
        sample_reviews=payload["sample_reviews"],
        nps_estimate=payload["nps_estimate"],
        processing_time_ms=int((time.monotonic() - started) * 1000),
        trial_user_id=trial_user_id,
        created_at=now,
        expires_at=now + TRIAL_IDEMPOTENCY_TTL,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)

    # Hydrate the global category labels into the saved payload —
    # the response model carries label_tr but we INSERT the row
    # before the label lookup so the persisted JSON also has labels.
    # The label hydration is best-effort: if the global categories
    # table is empty / unavailable the codes pass through as labels.
    label_map = await _load_global_category_labels(session)
    if label_map:
        for cat in row.top_categories:
            code = cat.get("code")
            if code and code in label_map:
                cat["label"] = label_map[code]
        # Re-assign so SQLAlchemy detects the JSONB mutation.
        row.top_categories = list(row.top_categories)
        await session.flush()

    _logger.info(
        "trial analysis completed email=%s rows=%d processing_ms=%d",
        row.email, row.total_rows, row.processing_time_ms,
    )
    return row


# Header patterns we recognize as "review text" for the trial path.
# Sprint 9.7 — smart_parser doesn't carry a review_text detector
# (the SaaS upload form lets the user pick the column explicitly),
# so the trial endpoint owns its own narrow heuristic. Patterns
# match after ``normalize_turkish`` folding so accent / case /
# I-İ variants all collapse onto the same key.
_TEXT_COLUMN_PATTERNS: tuple[str, ...] = (
    "yorum",
    "yorumlar",
    "comment",
    "comments",
    "review",
    "reviews",
    "metin",
    "text",
    "feedback",
    "geribildirim",
    "geri bildirim",
    "açıklama",
    "aciklama",
    "message",
    "mesaj",
)


def _detect_text_column(file_path: Path) -> str | None:
    """Pick the column that carries review text.

    Strategy:
      1. Try the known-header patterns first (``yorum`` / ``comment``
         / ``review`` / etc.). Most uploads land here on the first
         hit and we don't pay for a sample read.
      2. Fall back to "longest average cell length" — the column
         whose sampled values have the highest mean character count
         is overwhelmingly the review-text column in practice. Pulls
         ~50 rows via ``peek_header`` companions; cheap.

    Returns the original header (verbatim) so iter_rows can match
    it after normalize_turkish folding. None when the header peek
    fails or the file has no columns.
    """
    try:
        headers = peek_header(file_path)
    except (FileParseError, UnsupportedFormatError):
        return None
    if not headers:
        return None

    # Step 1 — pattern match on normalized headers.
    folded_patterns = {normalize_turkish(p) for p in _TEXT_COLUMN_PATTERNS}
    for header in headers:
        if normalize_turkish(header).strip() in folded_patterns:
            return header

    # Step 2 — single-column file is unambiguous.
    if len(headers) == 1:
        return headers[0]

    # Step 3 — fall back to "longest cell" heuristic. Sample the
    # file's first ~50 rows and rank columns by average cell length;
    # the text column is almost always the longest.
    try:
        from imga_api.services.smart_parser.sampler import sample_columns
        _, samples, _ = sample_columns(file_path)
    except (FileParseError, UnsupportedFormatError):
        return None
    best: tuple[str, float] | None = None
    for header, values in samples.items():
        non_empty = [v for v in values if v]
        if not non_empty:
            continue
        avg_len = sum(len(v) for v in non_empty) / len(non_empty)
        # Require at least 20 chars average to be plausibly review
        # text — guards against numeric / id columns winning.
        if avg_len < 20:
            continue
        if best is None or avg_len > best[1]:
            best = (header, avg_len)
    return best[0] if best is not None else None


def _extract_texts(file_path: Path, *, text_column: str) -> list[str]:
    """Pull every non-empty review text from the file. parse_file
    yields ParsedRow objects with a ``text`` attribute; we drop
    blanks. dimension_mapping stays None — trial demo doesn't
    enrich.

    Cap-checking is done by the caller (run_trial_analysis) so this
    helper stays small + reusable in tests.
    """
    texts: list[str] = []
    for row in iter_rows(
        file_path,
        text_column=text_column,
        source_column=None,
        dimension_mapping=None,
    ):
        if not row.text:
            continue
        stripped = row.text.strip()
        if not stripped:
            continue
        texts.append(stripped)
    return texts


def _build_response_payload(
    results: list[AnalysisResult],
) -> dict[str, Any]:
    """Aggregate the per-review results into the marketing-site
    response shape. See the marketing repo's trial result viewer
    for the exact frontend expectations.
    """
    # Sentiment distribution — counter over the 3-way label set.
    sentiment_counts: Counter[str] = Counter(
        r.sentiment_label for r in results
    )
    sentiment_distribution: dict[str, int] = {
        "POZITIF": sentiment_counts.get("POZITIF", 0),
        "NEGATIF": sentiment_counts.get("NEGATIF", 0),
        "NÖTR": sentiment_counts.get("NÖTR", 0),
    }

    # Top categories — group by classifier-assigned primary code.
    # Skip rows where the categorization didn't run (no classifier)
    # or where ``primary`` came back as ``belirsiz`` (an explicit
    # "no decision" code that doesn't help an operator triage).
    cat_counts: Counter[str] = Counter()
    for r in results:
        cat = r.categorization
        if cat is None:
            continue
        code = cat.primary
        if not code or code == "belirsiz":
            continue
        cat_counts[code] += 1
    top_categories: list[dict[str, Any]] = [
        {"code": code, "label": code, "count": count}
        for code, count in cat_counts.most_common(TOP_CATEGORIES_COUNT)
    ]

    # Sample reviews — try to surface a mix of sentiments so the
    # demo viewer doesn't only show 5 NEGATIF rows. We walk the
    # results in order and round-robin pick from each bucket up to
    # SAMPLE_REVIEW_COUNT total.
    sample_reviews = _pick_mixed_samples(results, SAMPLE_REVIEW_COUNT)

    # NPS estimate — heuristic on the sentiment counts since the
    # trial path doesn't ingest an actual NPS column. Standard NPS
    # formula on POZITIF (promoter proxy) - NEGATIF (detractor
    # proxy) over total, clamped to -100..100, int-rounded. None
    # when no rows.
    total = sum(sentiment_distribution.values())
    if total > 0:
        nps_est = round(
            (
                sentiment_distribution["POZITIF"]
                - sentiment_distribution["NEGATIF"]
            )
            / total
            * 100
        )
        nps_estimate: int | None = max(-100, min(100, nps_est))
    else:
        nps_estimate = None

    return {
        "sentiment_distribution": sentiment_distribution,
        "top_categories": top_categories,
        "sample_reviews": sample_reviews,
        "nps_estimate": nps_estimate,
    }


def _pick_mixed_samples(
    results: list[AnalysisResult], target: int
) -> list[dict[str, Any]]:
    """Round-robin sampling across the 3 sentiment buckets. Falls
    back to whatever's available when one bucket is empty."""
    buckets: dict[str, list[AnalysisResult]] = {
        "NEGATIF": [],
        "POZITIF": [],
        "NÖTR": [],
    }
    for r in results:
        buckets[r.sentiment_label].append(r)

    picked: list[dict[str, Any]] = []
    bucket_order = ["NEGATIF", "POZITIF", "NÖTR"]
    idx = 0
    while len(picked) < target:
        b = bucket_order[idx % len(bucket_order)]
        if buckets[b]:
            r = buckets[b].pop(0)
            cat_code = (
                r.categorization.primary
                if r.categorization is not None
                else None
            )
            picked.append(
                {
                    "text": r.text[:300],  # cap excerpt length
                    "sentiment": r.sentiment_label,
                    "primary_category": cat_code or "belirsiz",
                }
            )
        idx += 1
        # Stop if we've gone around every bucket and they're all empty.
        if idx >= len(bucket_order) * (target + 3) and not any(
            buckets[b] for b in bucket_order
        ):
            break
    return picked


async def _load_global_category_labels(
    session: AsyncSession,
) -> dict[str, str]:
    """Pull the global category code → label_tr map. RLS-safe:
    global categories have tenant_id IS NULL which every session
    can read regardless of app.current_tenant_id. Returns {} on
    error so the route still answers (codes pass through as labels).
    """
    try:
        rows = (
            await session.execute(
                select(Category.code, Category.label_tr).where(
                    Category.tenant_id.is_(None),
                    Category.deleted_at.is_(None),
                )
            )
        ).all()
    except Exception:
        # Defensive: never let a label-lookup failure block the trial
        # response. Codes are usable labels (just less polished).
        _logger.exception("failed to load category labels for trial response")
        return {}
    return {code: label for code, label in rows}


def serialize_for_response(row: TrialAnalysis) -> dict[str, Any]:
    """Marshal a persisted TrialAnalysis row into the response shape
    the marketing site consumes. Used by both the fresh-run and
    idempotent-replay paths so the on-the-wire JSON is byte-stable
    across them."""
    return {
        "sentiment_distribution": dict(row.sentiment_distribution),
        "top_categories": list(row.top_categories),
        "sample_reviews": list(row.sample_reviews),
        "nps_estimate": row.nps_estimate,
        "request_id": str(row.request_id),
        "processing_time_ms": row.processing_time_ms,
    }


@contextlib.asynccontextmanager
async def temp_upload_dir(base: Path) -> Any:
    """Tmp dir for the trial upload. Removed (with the file inside)
    on exit. The route uses this so the bytes touch disk only as
    long as parse + analyze need them."""
    tmp = base / f"trial-{uuid4()}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        yield tmp
    finally:
        with contextlib.suppress(OSError):
            for p in tmp.iterdir():
                p.unlink(missing_ok=True)
            tmp.rmdir()
