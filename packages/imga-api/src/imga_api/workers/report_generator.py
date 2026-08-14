"""Excel/CSV multi-sheet report generator.

Sprint 8.3.2. ``generate_report_job`` is the APScheduler entrypoint:
the route inserts a queued ``report_jobs`` row, schedules
``submit_report_job(scheduler, job_id)``, and the worker drains it
into ``/var/imga/reports/{tenant}/{id}.{ext}``.

Sheet layout (comprehensive):

    1. Tüm Analizler          — review-level rows
    2. Duygu Özeti             — sentiment label pivot
    3. Kategori Özeti          — category count + sentiment breakdown
    4. Override Katmanları     — override layer trace stats
    5. Çapraz Analiz           — category × sentiment matrix
    6. Bilet Özeti             — ticket-state aggregates

reviews_only ⇒ sheets 1-5; tickets_only ⇒ ticket sheet only.

CSV format: a zip archive with one ``<sheet>.csv`` per included sheet,
UTF-8 BOM so Turkish characters open correctly in Excel.

Concurrency: per-tenant lock owned by the worker context (same
primitives as the batch worker — re-using ``WorkerContext`` keeps the
pattern uniform). Reports are I/O-bound so a single in-flight job per
tenant is enough.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import zipfile
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import xlsxwriter
from imga_db import create_engine, create_session_factory, set_current_tenant
from imga_db.models import (
    Category,
    ReportFormat,
    ReportJob,
    ReportType,
    Review,
    Ticket,
    TicketState,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from imga_api.services.audit_service import AuditService
from imga_api.services.report_service import ReportFilters, ReportService
from imga_api.settings import ReportSettings

log = logging.getLogger("imga-api.workers.report")


_OVERRIDE_LABEL_TR: dict[str, str] = {
    "knowledge_base": "Bilgi Tabanı Kuralı",
    "critical": "Kritik Anahtar Kelime",
    "tier1": "Güçlü Negatif Sıfat",
    "sla": "SLA Tetikleyicisi",
    "tier2": "İkincil Tetikleyici",
}

_HEADER_FILL = "#1e40af"
_HEADER_FONT = "#ffffff"


# ---------------------------------------------------------------------------
# Worker context — independent from the batch worker's, but same pattern
# ---------------------------------------------------------------------------


class ReportContext:
    """Plumbing for the report worker. Engines + per-tenant locks live
    on the context so they bind to the constructing event loop (lifespan
    in prod, test loop in pytest)."""

    def __init__(
        self,
        *,
        admin_engine: AsyncEngine,
        app_engine: AsyncEngine,
        admin_session_factory: async_sessionmaker[AsyncSession],
        app_session_factory: async_sessionmaker[AsyncSession],
        settings: ReportSettings,
    ) -> None:
        self.admin_engine = admin_engine
        self.app_engine = app_engine
        self.admin_session_factory = admin_session_factory
        self.app_session_factory = app_session_factory
        self.settings = settings
        self.tenant_locks: dict[UUID, asyncio.Lock] = {}

    def lock_for(self, tenant_id: UUID) -> asyncio.Lock:
        lock = self.tenant_locks.get(tenant_id)
        if lock is None:
            lock = asyncio.Lock()
            self.tenant_locks[tenant_id] = lock
        return lock

    async def dispose(self) -> None:
        await self.admin_engine.dispose()
        await self.app_engine.dispose()


async def build_report_context(*, settings: ReportSettings) -> ReportContext:
    admin_engine = create_engine("admin")
    app_engine = create_engine("app")
    return ReportContext(
        admin_engine=admin_engine,
        app_engine=app_engine,
        admin_session_factory=create_session_factory(admin_engine),
        app_session_factory=create_session_factory(app_engine),
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def generate_report_job(job_id: UUID, context: ReportContext) -> None:
    """Pick up a queued report, render to disk, mark completed/failed."""
    tenant_id = await _read_tenant_id(job_id, context.admin_session_factory)
    if tenant_id is None:
        log.warning("report worker: job %s missing", job_id)
        return

    async with context.lock_for(tenant_id):
        try:
            await _run_report(job_id, tenant_id, context)
        except Exception as exc:
            log.exception("report worker: job %s crashed: %s", job_id, exc)
            await _mark_failed(job_id, tenant_id, context, reason=str(exc))


async def _read_tenant_id(
    job_id: UUID,
    factory: async_sessionmaker[AsyncSession],
) -> UUID | None:
    async with factory() as session, session.begin():
        stmt = select(ReportJob.tenant_id).where(ReportJob.id == job_id)
        return (await session.execute(stmt)).scalar_one_or_none()


async def _mark_failed(
    job_id: UUID,
    tenant_id: UUID,
    context: ReportContext,
    *,
    reason: str,
) -> None:
    async with context.admin_session_factory() as session, session.begin():
        await set_current_tenant(session, tenant_id)
        audit = AuditService(session)
        service = ReportService(session, audit, context.settings)
        try:
            await service.mark_failed(job_id=job_id, reason=reason)
        except Exception:
            log.exception("report worker: could not mark %s failed", job_id)


async def _run_report(
    job_id: UUID,
    tenant_id: UUID,
    context: ReportContext,
) -> None:
    # Step 1 — flip QUEUED → GENERATING and read the immutable job
    # parameters into local variables so we can release the admin
    # session before the (potentially slow) render phase.
    async with context.admin_session_factory() as admin_session, admin_session.begin():
        await set_current_tenant(admin_session, tenant_id)
        audit = AuditService(admin_session)
        service = ReportService(admin_session, audit, context.settings)
        job = await service.mark_generating(job_id)
        if job.status != "generating":
            log.info(
                "report worker: job %s in terminal state %s; skipping",
                job_id, job.status,
            )
            return
        report_type = ReportType(job.report_type)
        format_ = ReportFormat(job.format)
        filters = ReportFilters.from_json(job.filters)

    # Step 2 — gather rows under an RLS-bound app session.
    async with context.app_session_factory() as app_session, app_session.begin():
        await set_current_tenant(app_session, tenant_id)
        audit = AuditService(app_session)
        service = ReportService(app_session, audit, context.settings)
        review_rows, ticket_rows, category_lookup = await _fetch_rows(
            service=service,
            session=app_session,
            tenant_id=tenant_id,
            report_type=report_type,
            filters=filters,
        )

    # Step 3 — render outside any DB transaction.
    file_path = (
        context.settings.reports_dir / str(tenant_id) / f"{job_id}.{format_.value}"
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if format_ == ReportFormat.XLSX:
        _render_xlsx(
            path=file_path,
            report_type=report_type,
            review_rows=review_rows,
            ticket_rows=ticket_rows,
            category_lookup=category_lookup,
        )
    else:
        _render_csv_zip(
            path=file_path,
            report_type=report_type,
            review_rows=review_rows,
            ticket_rows=ticket_rows,
            category_lookup=category_lookup,
        )
    file_size_bytes = file_path.stat().st_size

    # Step 4 — finalise.
    async with context.admin_session_factory() as admin_session, admin_session.begin():
        await set_current_tenant(admin_session, tenant_id)
        audit = AuditService(admin_session)
        service = ReportService(admin_session, audit, context.settings)
        await service.mark_completed(
            job_id=job_id,
            file_path=str(file_path),
            file_size_bytes=file_size_bytes,
            row_count=len(review_rows) + len(ticket_rows),
        )


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------


async def _fetch_rows(
    *,
    service: ReportService,
    session: AsyncSession,
    tenant_id: UUID,
    report_type: ReportType,
    filters: ReportFilters,
) -> tuple[list[Review], list[Ticket], Mapping[str, str]]:
    """Returns (reviews, tickets, category_code → label_tr mapping).

    Empty list for the report-type-excluded surface, populated for the
    included one(s).
    """
    review_rows: list[Review] = []
    ticket_rows: list[Ticket] = []

    if report_type in (ReportType.COMPREHENSIVE, ReportType.REVIEWS_ONLY):
        review_stmt = select(Review).where(
            Review.tenant_id == tenant_id,
            Review.deleted_at.is_(None),
        )
        review_stmt = service.apply_review_filters(review_stmt, filters).order_by(
            Review.review_date.desc()
        )
        review_rows = list((await session.execute(review_stmt)).scalars())

    if report_type in (ReportType.COMPREHENSIVE, ReportType.TICKETS_ONLY):
        ticket_stmt = select(Ticket).where(
            Ticket.tenant_id == tenant_id,
            Ticket.deleted_at.is_(None),
        )
        ticket_stmt = service.apply_ticket_filters(ticket_stmt, filters).order_by(
            Ticket.opened_at.desc()
        )
        ticket_rows = list((await session.execute(ticket_stmt)).scalars())

    cat_stmt = select(Category.code, Category.label_tr).where(Category.deleted_at.is_(None))
    cat_rows = (await session.execute(cat_stmt)).all()
    category_lookup: dict[str, str] = {row[0]: row[1] for row in cat_rows}
    return review_rows, ticket_rows, category_lookup


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_xlsx(
    *,
    path: Path,
    report_type: ReportType,
    review_rows: list[Review],
    ticket_rows: list[Ticket],
    category_lookup: Mapping[str, str],
) -> None:
    workbook = xlsxwriter.Workbook(str(path))
    try:
        header_fmt = workbook.add_format({
            "bold": True,
            "bg_color": _HEADER_FILL,
            "font_color": _HEADER_FONT,
            "align": "center",
            "valign": "vcenter",
            "border": 1,
        })
        date_fmt = workbook.add_format({"num_format": "DD.MM.YYYY HH:MM"})
        pct_fmt = workbook.add_format({"num_format": "0.00%"})
        num_fmt = workbook.add_format({"num_format": "0.00"})

        if report_type in (ReportType.COMPREHENSIVE, ReportType.REVIEWS_ONLY):
            _sheet_reviews(
                workbook, review_rows, category_lookup,
                header_fmt=header_fmt, date_fmt=date_fmt, num_fmt=num_fmt,
            )
            _sheet_sentiment_summary(
                workbook, review_rows,
                header_fmt=header_fmt, pct_fmt=pct_fmt, num_fmt=num_fmt,
            )
            _sheet_category_summary(
                workbook, review_rows, category_lookup,
                header_fmt=header_fmt, pct_fmt=pct_fmt,
            )
            _sheet_override_layers(
                workbook, review_rows,
                header_fmt=header_fmt, num_fmt=num_fmt,
            )
            _sheet_cross_analysis(
                workbook, review_rows, category_lookup,
                header_fmt=header_fmt,
            )

        if report_type in (ReportType.COMPREHENSIVE, ReportType.TICKETS_ONLY):
            _sheet_tickets(
                workbook, ticket_rows,
                header_fmt=header_fmt, date_fmt=date_fmt,
            )
    finally:
        workbook.close()


def _sheet_reviews(
    workbook: Any,
    rows: list[Review],
    category_lookup: Mapping[str, str],
    *,
    header_fmt: Any,
    date_fmt: Any,
    num_fmt: Any,
) -> None:
    sheet = workbook.add_worksheet("Tüm Analizler")
    # İki tarih ayrı kolonda: "Yorum Tarihi" analizin ekseni (yüklenen
    # ``tarih`` kolonu), "Analiz Tarihi" ise yorumun ne zaman işlendiği.
    headers = [
        "Yorum Tarihi", "Analiz Tarihi", "Metin", "Duygu", "Skor (raw)",
        "Skor (final)", "Kategori", "Güven", "Override Katmanları",
        "Bilet #", "Kaynak",
    ]
    widths = [18, 18, 60, 12, 12, 12, 18, 10, 24, 16, 12]
    for col, label in enumerate(headers):
        sheet.write(0, col, label, header_fmt)
    sheet.freeze_panes(1, 0)
    sheet.autofilter(0, 0, max(0, len(rows)), len(headers) - 1)

    if not rows:
        sheet.write(1, 0, "Bu filtrelerle veri bulunamadı.")
        _set_widths(sheet, widths)
        return

    for r, review in enumerate(rows, start=1):
        sheet.write_datetime(r, 0, review.review_date.replace(tzinfo=None), date_fmt)
        sheet.write_datetime(r, 1, review.analyzed_at.replace(tzinfo=None), date_fmt)
        sheet.write_string(r, 2, review.text)
        sheet.write_string(r, 3, review.sentiment_label)
        score = float(review.sentiment_score)
        sheet.write_number(r, 4, score, num_fmt)
        sheet.write_number(r, 5, score, num_fmt)
        sheet.write_string(
            r, 6, category_lookup.get(review.primary_category, review.primary_category),
        )
        sheet.write_number(r, 7, float(review.primary_confidence), num_fmt)
        sheet.write_string(r, 8, _rule_layer_labels(review.overrides_applied))
        sheet.write_string(r, 9, str(review.ticket_id) if review.ticket_id else "")
        sheet.write_string(r, 10, "Toplu" if review.batch_job_id else "Manuel")

    _set_widths(sheet, widths)


def _sheet_sentiment_summary(
    workbook: Any,
    rows: list[Review],
    *,
    header_fmt: Any,
    pct_fmt: Any,
    num_fmt: Any,
) -> None:
    sheet = workbook.add_worksheet("Duygu Özeti")
    headers = ["Duygu", "Sayı", "Yüzde", "Ortalama Skor"]
    for col, label in enumerate(headers):
        sheet.write(0, col, label, header_fmt)
    sheet.freeze_panes(1, 0)

    counts: dict[str, int] = defaultdict(int)
    sums: dict[str, float] = defaultdict(float)
    for r in rows:
        counts[r.sentiment_label] += 1
        sums[r.sentiment_label] += float(r.sentiment_score)
    total = len(rows) or 1
    order = ["NEGATIF", "NÖTR", "POZITIF"]
    for i, label in enumerate(order, start=1):
        n = counts[label]
        sheet.write_string(i, 0, label)
        sheet.write_number(i, 1, n)
        sheet.write_number(i, 2, n / total, pct_fmt)
        avg = sums[label] / n if n else 0.0
        sheet.write_number(i, 3, avg, num_fmt)
    _set_widths(sheet, [12, 10, 12, 16])


def _sheet_category_summary(
    workbook: Any,
    rows: list[Review],
    category_lookup: Mapping[str, str],
    *,
    header_fmt: Any,
    pct_fmt: Any,
) -> None:
    sheet = workbook.add_worksheet("Kategori Özeti")
    headers = ["Kategori", "Sayı", "Yüzde", "NEGATİF", "NÖTR", "POZİTİF"]
    for col, label in enumerate(headers):
        sheet.write(0, col, label, header_fmt)
    sheet.freeze_panes(1, 0)

    cat_total: dict[str, int] = defaultdict(int)
    cat_breakdown: dict[str, dict[str, int]] = defaultdict(
        lambda: {"NEGATIF": 0, "NÖTR": 0, "POZITIF": 0}
    )
    for r in rows:
        cat_total[r.primary_category] += 1
        cat_breakdown[r.primary_category][r.sentiment_label] += 1
    total = len(rows) or 1
    sorted_cats = sorted(cat_total.items(), key=lambda kv: -kv[1])
    for i, (code, count) in enumerate(sorted_cats, start=1):
        sheet.write_string(i, 0, category_lookup.get(code, code))
        sheet.write_number(i, 1, count)
        sheet.write_number(i, 2, count / total, pct_fmt)
        sheet.write_number(i, 3, cat_breakdown[code]["NEGATIF"])
        sheet.write_number(i, 4, cat_breakdown[code]["NÖTR"])
        sheet.write_number(i, 5, cat_breakdown[code]["POZITIF"])
    _set_widths(sheet, [22, 10, 12, 12, 10, 12])


def _rule_layer_labels(overrides: list[dict[str, object]] | None) -> str:
    """Satırın kural-katmanı izlerinin Türkçe etiketleri, tetiklenme
    sırasıyla. reanalysis / user_correction* izleri bilinçli dışarıda:
    dashboard'daki override_stats de yalnız bu 5 katmanı sayar, rapor
    ile ekran aynı sözleşmeyi izler."""
    if not isinstance(overrides, list):
        return ""
    labels: list[str] = []
    for entry in overrides:
        if not isinstance(entry, dict):
            continue
        layer = entry.get("layer")
        if isinstance(layer, str) and layer in _OVERRIDE_LABEL_TR:
            labels.append(_OVERRIDE_LABEL_TR[layer])
    return ", ".join(labels)


def _sheet_override_layers(
    workbook: Any,
    rows: list[Review],
    *,
    header_fmt: Any,
    num_fmt: Any,
) -> None:
    sheet = workbook.add_worksheet("Override Katmanları")
    headers = ["Layer", "Tetiklenme", "Yön", "Ortalama Etki"]
    for col, label in enumerate(headers):
        sheet.write(0, col, label, header_fmt)
    sheet.freeze_panes(1, 0)

    # analytics_service.override_stats ile aynı savunmacı desen: dict
    # olmayan girdiler ve score'u sayı olmayanlar (ör. {"layer":
    # "reanalysis"} izi) atlanır; bilinmeyen katman kodu raporu
    # patlatmak yerine sessizce düşer.
    per_layer: dict[str, list[float]] = {code: [] for code in _OVERRIDE_LABEL_TR}
    for review in rows:
        arr = review.overrides_applied
        if not isinstance(arr, list):
            continue
        for entry in arr:
            if not isinstance(entry, dict):
                continue
            layer = entry.get("layer")
            score = entry.get("score")
            if (
                isinstance(layer, str)
                and layer in per_layer
                and isinstance(score, (int, float))
            ):
                per_layer[layer].append(float(score))

    for i, (code, label) in enumerate(_OVERRIDE_LABEL_TR.items(), start=1):
        scores = per_layer[code]
        count = len(scores)
        # Ortalama İŞARETLİ tutulur (dashboard'ın avg_impact'i mutlak
        # değer ortalamasıdır); yön de bu işaretten okunur.
        avg = sum(scores) / count if count else 0.0
        if count == 0 or avg == 0:
            direction = "—"
        elif avg < 0:
            direction = "−"
        else:
            direction = "+"
        sheet.write_string(i, 0, label)
        sheet.write_number(i, 1, count)
        sheet.write_string(i, 2, direction)
        sheet.write_number(i, 3, avg, num_fmt)
    _set_widths(sheet, [24, 14, 12, 16])


def _sheet_cross_analysis(
    workbook: Any,
    rows: list[Review],
    category_lookup: Mapping[str, str],
    *,
    header_fmt: Any,
) -> None:
    sheet = workbook.add_worksheet("Çapraz Analiz")
    sentiments = ["NEGATIF", "NÖTR", "POZITIF"]
    sheet.write(0, 0, "Kategori", header_fmt)
    for col, s in enumerate(sentiments, start=1):
        sheet.write(0, col, s, header_fmt)
    sheet.freeze_panes(1, 1)

    cat_breakdown: dict[str, dict[str, int]] = defaultdict(
        lambda: dict.fromkeys(sentiments, 0)
    )
    for r in rows:
        if r.sentiment_label in cat_breakdown[r.primary_category]:
            cat_breakdown[r.primary_category][r.sentiment_label] += 1
    sorted_cats = sorted(
        cat_breakdown.items(), key=lambda kv: -sum(kv[1].values())
    )
    for i, (code, breakdown) in enumerate(sorted_cats, start=1):
        sheet.write_string(i, 0, category_lookup.get(code, code))
        for col, s in enumerate(sentiments, start=1):
            sheet.write_number(i, col, breakdown[s])
    _set_widths(sheet, [22, 12, 10, 12])


def _sheet_tickets(
    workbook: Any,
    rows: list[Ticket],
    *,
    header_fmt: Any,
    date_fmt: Any,
) -> None:
    sheet = workbook.add_worksheet("Bilet Özeti")
    headers = ["Durum", "Sayı", "Ortalama Çözüm (gün)", "En Eski Açık (gün)"]
    for col, label in enumerate(headers):
        sheet.write(0, col, label, header_fmt)
    sheet.freeze_panes(1, 0)

    if not rows:
        sheet.write(1, 0, "Filtrelerle eşleşen bilet yok.")
        _set_widths(sheet, [16, 10, 22, 22])
        return

    by_state: dict[str, list[Ticket]] = defaultdict(list)
    for t in rows:
        by_state[str(t.state)].append(t)
    now = datetime.now(UTC)
    for i, state in enumerate(
        [str(s) for s in TicketState], start=1
    ):
        bucket = by_state.get(state, [])
        sheet.write_string(i, 0, state)
        sheet.write_number(i, 1, len(bucket))
        # Ortalama çözüm: resolved_at - opened_at, sadece resolve edilenler
        resolved = [t for t in bucket if t.resolved_at is not None]
        avg_resolution = (
            sum((t.resolved_at - t.opened_at).total_seconds() for t in resolved if t.resolved_at)
            / len(resolved) / 86400
        ) if resolved else 0
        sheet.write_number(i, 2, avg_resolution)
        # En eski açık (open + in_progress + pending_customer)
        if state in ("open", "in_progress", "pending_customer") and bucket:
            oldest_age_days = max(
                (now - t.opened_at).total_seconds() / 86400 for t in bucket
            )
        else:
            oldest_age_days = 0
        sheet.write_number(i, 3, round(oldest_age_days, 1))

    _ = date_fmt  # reserved for future use
    _set_widths(sheet, [16, 10, 22, 22])


def _set_widths(sheet: Any, widths: list[int]) -> None:
    for i, w in enumerate(widths):
        sheet.set_column(i, i, w)


def _render_csv_zip(
    *,
    path: Path,
    report_type: ReportType,
    review_rows: list[Review],
    ticket_rows: list[Ticket],
    category_lookup: Mapping[str, str],
) -> None:
    """Zip with one CSV per logical sheet. UTF-8 BOM so Excel opens
    Turkish characters correctly."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if report_type in (ReportType.COMPREHENSIVE, ReportType.REVIEWS_ONLY):
            zf.writestr("tum_analizler.csv", _csv_reviews(review_rows, category_lookup))
            zf.writestr("duygu_ozeti.csv", _csv_sentiment_summary(review_rows))
            zf.writestr("kategori_ozeti.csv", _csv_category_summary(review_rows, category_lookup))
        if report_type in (ReportType.COMPREHENSIVE, ReportType.TICKETS_ONLY):
            zf.writestr("bilet_ozeti.csv", _csv_tickets(ticket_rows))


def _csv_reviews(rows: list[Review], category_lookup: Mapping[str, str]) -> bytes:
    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM
    writer = csv.writer(buf)
    writer.writerow([
        "Yorum Tarihi", "Analiz Tarihi", "Metin", "Duygu", "Skor",
        "Kategori", "Güven", "Bilet #", "Kaynak",
    ])
    for r in rows:
        writer.writerow([
            r.review_date.strftime("%d.%m.%Y %H:%M"),
            r.analyzed_at.strftime("%d.%m.%Y %H:%M"),
            r.text,
            r.sentiment_label,
            f"{r.sentiment_score:.2f}",
            category_lookup.get(r.primary_category, r.primary_category),
            f"{r.primary_confidence:.2f}",
            str(r.ticket_id) if r.ticket_id else "",
            "Toplu" if r.batch_job_id else "Manuel",
        ])
    return buf.getvalue().encode("utf-8")


def _csv_sentiment_summary(rows: list[Review]) -> bytes:
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(["Duygu", "Sayı", "Yüzde"])
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.sentiment_label] += 1
    total = len(rows) or 1
    for label in ["NEGATIF", "NÖTR", "POZITIF"]:
        n = counts[label]
        writer.writerow([label, n, f"{n / total:.2%}"])
    return buf.getvalue().encode("utf-8")


def _csv_category_summary(
    rows: list[Review], category_lookup: Mapping[str, str]
) -> bytes:
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(["Kategori", "Sayı", "Yüzde"])
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.primary_category] += 1
    total = len(rows) or 1
    for code, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        writer.writerow([
            category_lookup.get(code, code),
            count,
            f"{count / total:.2%}",
        ])
    return buf.getvalue().encode("utf-8")


def _csv_tickets(rows: list[Ticket]) -> bytes:
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(["Durum", "Sayı"])
    counts: dict[str, int] = defaultdict(int)
    for t in rows:
        counts[str(t.state)] += 1
    for state in [str(s) for s in TicketState]:
        writer.writerow([state, counts.get(state, 0)])
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


async def recover_report_orphans(context: ReportContext) -> int:
    """At startup, any GENERATING row is a crash artefact (no live
    worker holds the in-memory tenant lock). Mark those FAILED so the
    UI shows an actionable state."""
    async with context.admin_session_factory() as session, session.begin():
        stmt = select(ReportJob.id, ReportJob.tenant_id).where(
            ReportJob.status == "generating"
        )
        rows = list((await session.execute(stmt)).all())
    for job_id, tenant_id in rows:
        await _mark_failed(
            job_id, tenant_id, context,
            reason="worker process restarted before this report finished",
        )
    return len(rows)


__all__ = [
    "ReportContext",
    "build_report_context",
    "generate_report_job",
    "recover_report_orphans",
]
