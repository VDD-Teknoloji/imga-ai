"""Aylık işlem adedi + katılım oranı (engagement) hesabı.

İş hikâyesi: bir kurum Mayıs'ta 100.000 işlem yapıp 5.000 yorum
topluyorsa katılım oranı %5'tir. Kurum yalnızca işlem adedini girer;
yorum sayısı ``reviews.review_date`` üzerinden aylık bucket'lanır
(yükleme tarihi değil — 3 aylık arşivi tek seferde yükleyen kurum
gerçek ay dağılımını görsün diye).

Bant değerlendirmesi: bantlar artan ``min_pct`` sıralı bir listedir;
bir oran, ``min_pct <= pct`` koşulunu sağlayan EN SON banda düşer.
Yani eşiğin tam üstündeki oran (%2 ve bant sınırı 2) üst banda gider.
Kurumun bandı yoksa ``DEFAULT_BANDS`` kullanılır — okuma sırasında
satır oluşturulmaz.

Servis transaction yönetmez; çağıran kendi ``async with
session.begin():`` bloğunu açar (kpi_goal_service ile aynı sözleşme).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from imga_db.models import Review, TenantEngagementSetting, TenantMonthlyMetric
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Varsayılan bantlar — kuruma özel satır yoksa API bunları döner.
# Sektöre göre değiştiği için süper yönetici kurum bazında ezer.
DEFAULT_BANDS: list[dict[str, Any]] = [
    {"min_pct": 0.0, "label": "Çok Kötü"},
    {"min_pct": 1.0, "label": "Kötü"},
    {"min_pct": 2.0, "label": "Orta"},
    {"min_pct": 5.0, "label": "Çok İyi"},
]

DEFAULT_MONTH_WINDOW = 12


class EngagementError(Exception):
    """Servis katmanı hatası; route 4xx'e çevirir."""


class MonthlyMetricNotFound(EngagementError):
    """Silinmek istenen ay kurumda yok."""


@dataclass(frozen=True, slots=True)
class EngagementRow:
    """Tablonun tek satırı. ``transaction_count`` girilmemişse
    ``engagement_pct`` / band alanları ``None`` — UI bunu "veri girin"
    çağrısına çevirir."""

    period_month: date
    transaction_count: int | None
    review_count: int
    engagement_pct: float | None
    band_label: str | None
    band_index: int | None


def normalize_month(value: date) -> date:
    """Ayın ilk günü. DB'deki CheckConstraint ikinci savunma hattı;
    kullanıcı ayın 17'sini gönderdiğinde 400 yerine doğru ayı yazarız."""
    return value.replace(day=1)


def month_floor(value: datetime) -> date:
    return date(value.year, value.month, 1)


def add_months(anchor: date, delta: int) -> date:
    """Ay aritmetiği — ``timedelta`` gün bazlı olduğu için ay ekleme
    için kullanılamaz (28/31 gün sapması)."""
    total = anchor.year * 12 + (anchor.month - 1) + delta
    return date(total // 12, total % 12 + 1, 1)


def resolve_band(
    engagement_pct: float | None,
    bands: list[dict[str, Any]],
) -> tuple[int | None, str | None]:
    """``min_pct <= pct`` sağlayan en son bant. Bantlar artan sıralı
    kabul edilir (Pydantic doğrular); yine de sıralayarak okuruz ki
    elle yazılmış bir JSONB satırı hesabı bozmasın."""
    if engagement_pct is None or not bands:
        return None, None
    ordered = sorted(bands, key=lambda b: float(b["min_pct"]))
    match_index: int | None = None
    for index, band in enumerate(ordered):
        if engagement_pct >= float(band["min_pct"]):
            match_index = index
        else:
            break
    if match_index is None:
        return None, None
    return match_index, str(ordered[match_index]["label"])


def compute_engagement_pct(
    review_count: int,
    transaction_count: int | None,
) -> float | None:
    """İşlem adedi yoksa VEYA sıfırsa oran tanımsızdır. Sıfır özellikle
    önemli: "0 işlem" girmiş bir kurum ZeroDivisionError yerine boş
    hücre görmeli."""
    if transaction_count is None or transaction_count <= 0:
        return None
    return round((review_count / transaction_count) * 100.0, 4)


class EngagementService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- aylık işlem adedi (kurum girer) ------------------------------

    async def list_monthly_metrics(
        self,
        *,
        tenant_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[TenantMonthlyMetric]:
        stmt = select(TenantMonthlyMetric).where(
            TenantMonthlyMetric.tenant_id == tenant_id
        )
        if date_from is not None:
            stmt = stmt.where(
                TenantMonthlyMetric.period_month >= normalize_month(date_from)
            )
        if date_to is not None:
            stmt = stmt.where(
                TenantMonthlyMetric.period_month <= normalize_month(date_to)
            )
        stmt = stmt.order_by(TenantMonthlyMetric.period_month.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def upsert_monthly_metric(
        self,
        *,
        tenant_id: UUID,
        period_month: date,
        transaction_count: int,
        set_by_user_id: UUID | None,
        notes: str | None = None,
    ) -> TenantMonthlyMetric:
        """Ay başına tek satır: varsa güncelle, yoksa aç. Select-then-write
        (ON CONFLICT değil) — UNIQUE kısıtı zaten var, ama audit alanlarını
        (``set_by_user_id``) her yazımda tazelemek istiyoruz."""
        month = normalize_month(period_month)
        existing = (
            await self._session.execute(
                select(TenantMonthlyMetric)
                .where(TenantMonthlyMetric.tenant_id == tenant_id)
                .where(TenantMonthlyMetric.period_month == month)
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.transaction_count = transaction_count
            existing.notes = notes
            existing.set_by_user_id = set_by_user_id
            await self._session.flush()
            return existing

        row = TenantMonthlyMetric(
            tenant_id=tenant_id,
            period_month=month,
            transaction_count=transaction_count,
            set_by_user_id=set_by_user_id,
            notes=notes,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def delete_monthly_metric(
        self,
        *,
        tenant_id: UUID,
        period_month: date,
    ) -> None:
        month = normalize_month(period_month)
        row = (
            await self._session.execute(
                select(TenantMonthlyMetric)
                .where(TenantMonthlyMetric.tenant_id == tenant_id)
                .where(TenantMonthlyMetric.period_month == month)
            )
        ).scalar_one_or_none()
        if row is None:
            raise MonthlyMetricNotFound(
                f"monthly metric {month.isoformat()} not in tenant {tenant_id}"
            )
        await self._session.delete(row)
        await self._session.flush()

    # --- bantlar (süper yönetici düzenler) ----------------------------

    async def get_settings_row(
        self, *, tenant_id: UUID
    ) -> TenantEngagementSetting | None:
        return (
            await self._session.execute(
                select(TenantEngagementSetting).where(
                    TenantEngagementSetting.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()

    async def get_bands(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        """Kuruma özel bantlar, yoksa varsayılan. Okuma satır AÇMAZ."""
        row = await self.get_settings_row(tenant_id=tenant_id)
        if row is None or not row.bands:
            return [dict(band) for band in DEFAULT_BANDS]
        return [dict(band) for band in row.bands]

    async def set_bands(
        self,
        *,
        tenant_id: UUID,
        bands: list[dict[str, Any]],
        updated_by_user_id: UUID | None,
    ) -> TenantEngagementSetting:
        row = await self.get_settings_row(tenant_id=tenant_id)
        if row is None:
            row = TenantEngagementSetting(
                tenant_id=tenant_id,
                bands=bands,
                updated_by_user_id=updated_by_user_id,
            )
            self._session.add(row)
        else:
            row.bands = bands
            row.updated_by_user_id = updated_by_user_id
        await self._session.flush()
        return row

    # --- katılım tablosu ----------------------------------------------

    async def monthly_review_counts(
        self,
        *,
        tenant_id: UUID,
        month_from: date,
        month_to: date,
    ) -> dict[date, int]:
        """``review_date`` ekseninde aylık yorum sayısı. Soft-delete
        edilmiş satırlar hariç. Bucket sınırı ``month_to``nun bir sonraki
        ayının ilk günü — ``<`` ile karşılaştırınca ayın son gününün
        saat bileşeni kaybolmaz."""
        upper = add_months(month_to, 1)
        bucket = func.date_trunc("month", Review.review_date)
        stmt = (
            select(bucket.label("bucket"), func.count().label("total"))
            .where(Review.tenant_id == tenant_id)
            .where(Review.deleted_at.is_(None))
            .where(Review.review_date >= month_from)
            .where(Review.review_date < upper)
            .group_by(bucket)
        )
        rows = (await self._session.execute(stmt)).all()
        out: dict[date, int] = {}
        for bucket_value, total in rows:
            if bucket_value is None:
                continue
            key = (
                month_floor(bucket_value)
                if isinstance(bucket_value, datetime)
                else date(bucket_value.year, bucket_value.month, 1)
            )
            out[key] = int(total)
        return out

    async def build_engagement_rows(
        self,
        *,
        tenant_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        today: date | None = None,
    ) -> tuple[list[EngagementRow], list[dict[str, Any]]]:
        """Ay serisini Python'da üretip iki sözlüğü (işlem adedi, yorum
        sayısı) sol-birleştirir. Varsayılan pencere son 12 ay (bu ay
        dahil). Yorumu olan ama işlem adedi girilmemiş ay da satır
        olarak döner — oran ``None``, UI "veri girin" der."""
        anchor = today or datetime.now(UTC).date()
        month_to = normalize_month(date_to) if date_to else normalize_month(anchor)
        month_from = (
            normalize_month(date_from)
            if date_from
            else add_months(month_to, -(DEFAULT_MONTH_WINDOW - 1))
        )
        if month_from > month_to:
            month_from = month_to

        metrics = await self.list_monthly_metrics(
            tenant_id=tenant_id, date_from=month_from, date_to=month_to
        )
        counts = await self.monthly_review_counts(
            tenant_id=tenant_id, month_from=month_from, month_to=month_to
        )
        bands = await self.get_bands(tenant_id=tenant_id)

        by_month = {m.period_month: m for m in metrics}
        rows: list[EngagementRow] = []
        cursor = month_to
        while cursor >= month_from:
            metric = by_month.get(cursor)
            transaction_count = (
                int(metric.transaction_count) if metric is not None else None
            )
            review_count = counts.get(cursor, 0)
            pct = compute_engagement_pct(review_count, transaction_count)
            band_index, band_label = resolve_band(pct, bands)
            rows.append(
                EngagementRow(
                    period_month=cursor,
                    transaction_count=transaction_count,
                    review_count=review_count,
                    engagement_pct=pct,
                    band_label=band_label,
                    band_index=band_index,
                )
            )
            cursor = add_months(cursor, -1)
        return rows, bands


__all__ = [
    "DEFAULT_BANDS",
    "DEFAULT_MONTH_WINDOW",
    "EngagementError",
    "EngagementRow",
    "EngagementService",
    "MonthlyMetricNotFound",
    "add_months",
    "compute_engagement_pct",
    "normalize_month",
    "resolve_band",
]
