"""Tenant-scoped living documents, operational context and retention workspace."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from imga_db.models import (
    CustomerAccount,
    CustomerObservation,
    IntelligenceRevision,
    Review,
    ReviewFact,
    Tenant,
    UserTenantRole,
)
from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, bind_tenant, require_role
from imga_api.db_deps import get_app_session
from imga_api.services.audit_service import AuditService
from imga_api.services.category_codes import valid_primary_codes
from imga_api.services.churn_scoring import score_customer
from imga_api.services.company_intelligence import diagnose_company, published_context
from imga_api.services.intelligence_schemas import (
    CompanyContext,
    CustomerProfile,
    CustomerUpdate,
    DocumentKind,
    DocumentUpdate,
    PrdDocument,
    ReviewSignals,
)
from imga_api.services.prd_service import export_markdown, interview, starter_document

router = APIRouter(prefix="/tenants/me/intelligence", tags=["Company Intelligence"])
_Reader = Depends(
    require_role(UserTenantRole.TENANT_ADMIN, UserTenantRole.ANALYST, UserTenantRole.VIEWER)
)
_Writer = Depends(require_role(UserTenantRole.TENANT_ADMIN, UserTenantRole.ANALYST))
_Admin = Depends(require_role(UserTenantRole.TENANT_ADMIN))
Session = Annotated[AsyncSession, Depends(get_app_session)]
MAX_CUSTOMERS = 5000


def _tenant(current: CurrentUser) -> UUID:
    if current.active_tenant_id is None:
        raise HTTPException(400, "Aktif kurum gerekli.")
    return current.active_tenant_id


async def _lock_tenant(session: AsyncSession, current: CurrentUser) -> Tenant:
    await bind_tenant(session, current)
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == _tenant(current)).with_for_update())
    ).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(404, "Kurum bulunamadı.")
    return tenant


async def _latest(
    session: AsyncSession, tenant_id: UUID, kind: DocumentKind
) -> IntelligenceRevision | None:
    return (
        await session.execute(
            select(IntelligenceRevision)
            .where(IntelligenceRevision.tenant_id == tenant_id, IntelligenceRevision.kind == kind)
            .order_by(IntelligenceRevision.revision.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _document(row: IntelligenceRevision | None, kind: DocumentKind) -> dict[str, Any]:
    content = (
        row.content
        if row
        else (
            CompanyContext().model_dump(mode="json")
            if kind == "company"
            else starter_document().model_dump(mode="json")
        )
    )
    result: dict[str, Any] = {
        "kind": kind,
        "revision": row.revision if row else 0,
        "status": row.status if row else "draft",
        "content": content,
        "created_at": row.created_at if row else None,
        "actor_id": row.actor_id if row else None,
    }
    if kind == "prd":
        result["interview"] = interview(PrdDocument.model_validate(content))
    return result


@router.get("/documents/{kind}")
async def get_document(
    kind: DocumentKind, current: Annotated[CurrentUser, _Reader], session: Session
) -> dict[str, Any]:
    async with session.begin():
        await bind_tenant(session, current)
        return _document(await _latest(session, _tenant(current), kind), kind)


@router.put("/documents/{kind}")
async def save_document(
    kind: DocumentKind,
    body: DocumentUpdate,
    current: Annotated[CurrentUser, _Writer],
    session: Session,
) -> dict[str, Any]:
    if (kind == "company") != isinstance(body.content, CompanyContext):
        raise HTTPException(422, "Belge türü ve içerik eşleşmiyor.")
    if body.status == "approved":
        if current.active_role != "tenant_admin" and not current.is_super_admin:
            raise HTTPException(403, "Yayınlama için kurum yöneticisi gerekli.")
        if (
            isinstance(body.content, PrdDocument)
            and not interview(body.content)["ready_for_approval"]
        ):
            raise HTTPException(422, "PRD onayı için kapsam içindeki bölümleri doğrulayın.")
        if isinstance(body.content, CompanyContext) and not body.content.name:
            raise HTTPException(422, "Yayınlama için şirket adı gerekli.")
    async with session.begin():
        tenant = await _lock_tenant(session, current)
        latest = await _latest(session, tenant.id, kind)
        version = latest.revision if latest else 0
        if version != body.expected_revision:
            raise HTTPException(409, "Belge değişti. Son sürümü açıp düzenlemenizi birleştirin.")
        if isinstance(body.content, CompanyContext) and body.status == "approved":
            known_codes = await valid_primary_codes(session, tenant.id)
            unknown_codes = {
                code for process in body.content.processes for code in process.category_codes
            } - known_codes
            if unknown_codes:
                raise HTTPException(
                    422, "Bilinmeyen süreç kategorileri: " + ", ".join(sorted(unknown_codes))
                )
        row = IntelligenceRevision(
            tenant_id=tenant.id,
            kind=kind,
            revision=version + 1,
            status=body.status,
            content=body.content.model_dump(mode="json"),
            actor_id=current.user_id,
        )
        session.add(row)
        if kind == "company" and body.status == "approved":
            tenant.settings = {
                **(tenant.settings or {}),
                "company_intelligence": row.content,
                "company_intelligence_revision": row.revision,
            }
        await session.flush()
        await AuditService(session).log(
            action="intelligence.document.saved",
            resource_type="intelligence_document",
            tenant_id=tenant.id,
            actor_user_id=current.user_id,
            details={"kind": kind, "revision": row.revision, "status": row.status},
        )
        return _document(row, kind)


@router.get("/documents/{kind}/history")
async def document_history(
    kind: DocumentKind,
    current: Annotated[CurrentUser, _Reader],
    session: Session,
    before: int | None = Query(default=None, ge=1),
) -> list[dict[str, Any]]:
    async with session.begin():
        await bind_tenant(session, current)
        stmt = select(IntelligenceRevision).where(
            IntelligenceRevision.tenant_id == _tenant(current), IntelligenceRevision.kind == kind
        )
        if before is not None:
            stmt = stmt.where(IntelligenceRevision.revision < before)
        rows = (
            (await session.execute(stmt.order_by(IntelligenceRevision.revision.desc()).limit(20)))
            .scalars()
            .all()
        )
        return [_document(row, kind) for row in rows]


@router.get("/prd/export", response_class=PlainTextResponse)
async def download_prd(
    current: Annotated[CurrentUser, _Reader], session: Session
) -> PlainTextResponse:
    async with session.begin():
        await bind_tenant(session, current)
        row = await _latest(session, _tenant(current), "prd")
        document = PrdDocument.model_validate(row.content) if row else starter_document()
        return PlainTextResponse(
            export_markdown(document, row.revision if row else 0),
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="imga-prd.md"'},
        )


@router.get("/company/diagnostics")
async def company_diagnostics(
    current: Annotated[CurrentUser, _Reader], session: Session
) -> dict[str, Any]:
    async with session.begin():
        await bind_tenant(session, current)
        tenant = await session.get(Tenant, _tenant(current))
        settings = tenant.settings if tenant else {}
        context = CompanyContext.model_validate(published_context(settings))
        result = await diagnose_company(session, _tenant(current), context)
        result["published_revision"] = settings.get("company_intelligence_revision", 0)
        return result


async def _review_signals(session: AsyncSession, tenant_id: UUID) -> dict[str, ReviewSignals]:
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(
                Review.customer_external_id,
                func.count(),
                func.count().filter(Review.sentiment_label == "NEGATIF"),
                func.count().filter(ReviewFact.sla_resolution_status == "violated"),
                func.count().filter(Review.nps_score <= 6),
            )
            .select_from(Review)
            .outerjoin(
                ReviewFact,
                (ReviewFact.review_id == Review.id) & (ReviewFact.tenant_id == Review.tenant_id),
            )
            .where(
                Review.tenant_id == tenant_id,
                Review.deleted_at.is_(None),
                Review.quality_flag.is_(None),
                Review.customer_external_id.is_not(None),
                Review.review_date >= now - timedelta(days=30),
                or_(
                    Review.analysis_profile.is_(None),
                    Review.analysis_profile != "mena",
                    (Review.primary_confidence >= 0.6)
                    & Review.analysis_language.in_(["ar", "ur", "tr", "en"]),
                ),
                Review.review_date < now,
            )
            .group_by(Review.customer_external_id)
        )
    ).all()
    return {
        str(key): ReviewSignals(total=total, negative=negative, sla_violations=sla, low_nps=nps)
        for key, total, negative, sla, nps in rows
    }


@router.get("/customers")
async def list_customers(
    current: Annotated[CurrentUser, _Reader],
    session: Session,
    search: str = Query(default="", max_length=128),
    band: Literal["all", "unknown", "low", "watch", "high", "critical", "inactive"] = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    async with session.begin():
        await bind_tenant(session, current)
        rows = (
            (
                await session.execute(
                    select(CustomerAccount)
                    .where(CustomerAccount.tenant_id == _tenant(current))
                    .limit(MAX_CUSTOMERS + 1)
                )
            )
            .scalars()
            .all()
        )
        if len(rows) > MAX_CUSTOMERS:
            raise HTTPException(
                422,
                "Bu çalışma alanı en çok 5000 müşteri destekler; bölümlenmiş değerlendirme gerekli.",
            )
        signals = await _review_signals(session, _tenant(current))
        now = datetime.now(UTC).date()
        items: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for row in rows:
            profile = CustomerProfile.model_validate(row.profile)
            risk = score_customer(profile, signals.get(row.external_id, ReviewSignals()), as_of=now)
            counts[risk.band] = counts.get(risk.band, 0) + 1
            if band != "all" and risk.band != band:
                continue
            if (
                search
                and search.casefold()
                not in f"{profile.external_id} {profile.name} {profile.segment}".casefold()
            ):
                continue
            items.append(
                {
                    "revision": row.revision,
                    "profile": row.profile,
                    "risk": risk.model_dump(mode="json"),
                }
            )
        items.sort(
            key=lambda item: (
                -(item["risk"]["score"] if item["risk"]["score"] is not None else -1),
                item["profile"]["external_id"],
            )
        )
        total = len(items)
        return {
            "items": items[(page - 1) * page_size : page * page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "counts": counts,
            "account_count": len(rows),
            "capacity": MAX_CUSTOMERS,
            "method": "rules-v1",
            "is_probability": False,
        }


async def _save_customer(
    session: AsyncSession,
    current: CurrentUser,
    profile: CustomerProfile,
    expected: int | None,
    signals: dict[str, ReviewSignals],
) -> dict[str, Any]:
    key = (_tenant(current), profile.external_id)
    row = await session.get(CustomerAccount, key)
    version = row.revision if row else 0
    if expected is not None and expected != version:
        raise HTTPException(409, f"Müşteri kaydı değişti: {profile.external_id}")
    if row and profile.observed_on < CustomerProfile.model_validate(row.profile).observed_on:
        raise HTTPException(
            409, f"Eski gözlem güncel verinin üstüne yazılamaz: {profile.external_id}"
        )
    risk = score_customer(
        profile, signals.get(profile.external_id, ReviewSignals()), as_of=datetime.now(UTC).date()
    )
    payload = profile.model_dump(mode="json")
    if row is None:
        row = CustomerAccount(tenant_id=key[0], external_id=key[1], revision=1, profile=payload)
        session.add(row)
    else:
        row.profile = payload
        row.revision = version + 1
    await session.flush()
    session.add(
        CustomerObservation(
            tenant_id=key[0],
            external_id=key[1],
            revision=row.revision,
            profile=payload,
            risk=risk.model_dump(mode="json"),
            actor_id=current.user_id,
        )
    )
    return {"revision": row.revision, "profile": payload, "risk": risk.model_dump(mode="json")}


@router.put("/customers/{external_id}")
async def save_customer(
    external_id: str,
    body: CustomerUpdate,
    current: Annotated[CurrentUser, _Writer],
    session: Session,
) -> dict[str, Any]:
    if external_id != body.profile.external_id:
        raise HTTPException(422, "Müşteri kimlikleri eşleşmiyor.")
    async with session.begin():
        await _lock_tenant(session, current)
        count = (
            await session.execute(
                select(func.count())
                .select_from(CustomerAccount)
                .where(CustomerAccount.tenant_id == _tenant(current))
            )
        ).scalar_one()
        if body.expected_revision == 0 and count >= MAX_CUSTOMERS:
            raise HTTPException(422, "5000 müşteri sınırına ulaşıldı.")
        return await _save_customer(
            session,
            current,
            body.profile,
            body.expected_revision,
            await _review_signals(session, _tenant(current)),
        )


@router.get("/customers/{external_id}/history")
async def customer_history(
    external_id: str,
    current: Annotated[CurrentUser, _Reader],
    session: Session,
    before: int | None = Query(default=None, ge=1),
) -> list[dict[str, Any]]:
    async with session.begin():
        await bind_tenant(session, current)
        stmt = select(CustomerObservation).where(
            CustomerObservation.tenant_id == _tenant(current),
            CustomerObservation.external_id == external_id,
        )
        if before is not None:
            stmt = stmt.where(CustomerObservation.revision < before)
        rows = (
            (await session.execute(stmt.order_by(CustomerObservation.revision.desc()).limit(20)))
            .scalars()
            .all()
        )
        return [
            {
                "revision": row.revision,
                "profile": row.profile,
                "risk": row.risk,
                "created_at": row.created_at,
            }
            for row in rows
        ]


@router.delete("/customers/{external_id}", status_code=204)
async def delete_customer(
    external_id: str, current: Annotated[CurrentUser, _Admin], session: Session
) -> None:
    async with session.begin():
        await _lock_tenant(session, current)
        # Erase history via composite cascade and detach legacy review identities.
        await session.execute(
            update(Review)
            .where(Review.tenant_id == _tenant(current), Review.customer_external_id == external_id)
            .values(customer_external_id=None)
        )
        await session.execute(
            delete(CustomerAccount).where(
                CustomerAccount.tenant_id == _tenant(current),
                CustomerAccount.external_id == external_id,
            )
        )
        await AuditService(session).log(
            action="intelligence.customer.erased",
            resource_type="customer_account",
            tenant_id=_tenant(current),
            actor_user_id=current.user_id,
        )


@router.get("/customer-import/template", response_class=PlainTextResponse)
async def customer_template(current: Annotated[CurrentUser, _Writer]) -> PlainTextResponse:
    _tenant(current)
    return PlainTextResponse(
        "external_id,name,source,observed_on,lifecycle,last_activity_on,expected_activity_days,orders_current_30d,orders_previous_30d,usage_current_30d,usage_previous_30d,overdue_invoices,cancellation_requested,renewal_on,owner,next_action,follow_up_on,outcome\n",
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="imga-customers.csv"'},
    )


def parse_customer_csv(raw: bytes) -> list[CustomerProfile]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        fields = reader.fieldnames or []
        if (
            not fields
            or len(set(fields)) != len(fields)
            or not {"external_id", "name", "source", "observed_on"}.issubset(fields)
        ):
            raise ValueError(
                "Benzersiz başlıklar ve external_id,name,source,observed_on kolonları gerekli."
            )
        if set(fields) - CustomerProfile.model_fields.keys():
            raise ValueError("CSV tanınmayan kolon içeriyor.")
        profiles: list[CustomerProfile] = []
        seen: set[str] = set()
        for line, record in enumerate(reader, 2):
            if len(profiles) >= MAX_CUSTOMERS:
                raise ValueError("CSV en çok 5000 müşteri içerebilir.")
            if None in record:
                raise ValueError(f"Satır {line}: kolon sayısı başlıkla eşleşmiyor.")
            values = {
                key: value for key, value in record.items() if value is not None and value.strip()
            }
            try:
                profile = CustomerProfile.model_validate(values)
            except ValidationError as exc:
                # Pydantic's input values may contain PII; return locations, not the raw row.
                locations = ", ".join(
                    ".".join(str(part) for part in error["loc"]) for error in exc.errors()
                )
                raise ValueError(
                    f"Satır {line}: geçersiz alanlar ({locations}). Tarihler YYYY-MM-DD olmalı."
                ) from exc
            if profile.external_id in seen:
                raise ValueError(f"Satır {line}: tekrarlanan müşteri kimliği.")
            seen.add(profile.external_id)
            profiles.append(profile)
        if not profiles:
            raise ValueError("CSV müşteri kaydı içermiyor.")
        return profiles
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("UTF-8 kodlanmış, virgülle ayrılmış CSV gerekli.") from exc


@router.post("/customer-import")
async def import_customers(
    file: UploadFile, current: Annotated[CurrentUser, _Writer], session: Session
) -> dict[str, int]:
    raw = await file.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "CSV en çok 5 MiB olabilir.")
    try:
        profiles = parse_customer_csv(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    async with session.begin():
        await _lock_tenant(session, current)
        existing = {
            row.external_id: row
            for row in (
                await session.execute(
                    select(CustomerAccount).where(CustomerAccount.tenant_id == _tenant(current))
                )
            )
            .scalars()
            .all()
        }
        if len(existing.keys() | {profile.external_id for profile in profiles}) > MAX_CUSTOMERS:
            raise HTTPException(422, "Kurum başına 5000 müşteri sınırı aşılır.")
        signals = await _review_signals(session, _tenant(current))
        accounts: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for profile in profiles:
            previous = existing.get(profile.external_id)
            if (
                previous
                and profile.observed_on
                < CustomerProfile.model_validate(previous.profile).observed_on
            ):
                raise HTTPException(
                    409, f"Eski gözlem güncel verinin üstüne yazılamaz: {profile.external_id}"
                )
            revision = previous.revision + 1 if previous else 1
            data = {
                "tenant_id": _tenant(current),
                "external_id": profile.external_id,
                "revision": revision,
                "profile": profile.model_dump(mode="json"),
            }
            accounts.append({**data, "updated_at": now})
            risk = score_customer(
                profile, signals.get(profile.external_id, ReviewSignals()), as_of=now.date()
            )
            observations.append(
                {**data, "risk": risk.model_dump(mode="json"), "actor_id": current.user_id}
            )
        # Keep DB round trips bounded; the tenant lock protects the read/version/upsert sequence.
        for offset in range(0, len(accounts), 500):
            stmt = pg_insert(CustomerAccount).values(accounts[offset : offset + 500])
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["tenant_id", "external_id"],
                    set_={
                        "profile": stmt.excluded.profile,
                        "revision": stmt.excluded.revision,
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
            )
            await session.execute(
                pg_insert(CustomerObservation).values(observations[offset : offset + 500])
            )
        await AuditService(session).log(
            action="intelligence.customers.imported",
            resource_type="customer_account",
            tenant_id=_tenant(current),
            actor_user_id=current.user_id,
            details={"count": len(profiles)},
        )
        return {"imported": len(profiles)}
