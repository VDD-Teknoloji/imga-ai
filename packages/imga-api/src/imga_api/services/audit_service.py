"""AuditService — append-only writes to audit_logs.

Every security-sensitive action (user create, invitation, role change,
tenant settings change, login attempt) goes through this service so the
caller doesn't need to remember the column layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from imga_db.models import AuditLog, Tenant, User
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class AuditLogRow:
    """One ``audit_logs`` row + the tenant/user names the C4/B2
    super-admin log viewer needs (2026-08-20). Built via LEFT JOINs
    in ``AuditService.list`` — ``tenant_id`` / ``actor_user_id`` are
    already nullable on the model (super-admin / pre-tenant actions,
    deactivated actors), so the joined names follow suit."""

    id: UUID
    tenant_id: UUID | None
    tenant_name: str | None
    actor_user_id: UUID | None
    actor_email: str | None
    action: str
    resource_type: str
    resource_id: UUID | None
    ip_address: str | None
    created_at: datetime


class AuditService:
    """Append-only audit log writer + the super-admin read surface.

    Reads happen elsewhere (RLS-scoped queries against audit_logs) for
    tenant-scoped call sites; ``list`` here is the cross-tenant admin
    view (BYPASSRLS session, caller's responsibility). Audit logs are
    tenant-scoped when possible: a NULL tenant_id is reserved for
    super-admin / pre-tenant actions.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
            tenant_id=tenant_id,
            details=details or {},
            ip_address=ip_address,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def list(
        self,
        *,
        tenant_id: UUID | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditLogRow], int]:
        """Filtered, paginated cross-tenant listing for
        ``GET /admin/audit-logs`` (C4/B2, 2026-08-20). Caller (the
        route) is responsible for the super-admin check and for
        running this on the BYPASSRLS admin session — a plain
        ``AuditLog`` select has no RLS policy of its own to lean on.

        ``action`` is a case-insensitive substring match (ILIKE), not
        an exact match — the admin UI filters by a fragment like
        "tenant." or "login" across many concrete action strings.
        ``date_to`` is compared with ``<`` (exclusive) — pass the
        instant right after the window you want included.
        """
        filters: list[Any] = []
        if tenant_id is not None:
            filters.append(AuditLog.tenant_id == tenant_id)
        if action is not None:
            filters.append(AuditLog.action.ilike(f"%{action}%"))
        if date_from is not None:
            filters.append(AuditLog.created_at >= date_from)
        if date_to is not None:
            filters.append(AuditLog.created_at < date_to)

        count_stmt = select(func.count()).select_from(AuditLog).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one() or 0

        list_stmt = (
            select(
                AuditLog.id,
                AuditLog.tenant_id,
                Tenant.name,
                AuditLog.actor_user_id,
                User.email,
                AuditLog.action,
                AuditLog.resource_type,
                AuditLog.resource_id,
                AuditLog.ip_address,
                AuditLog.created_at,
            )
            .outerjoin(Tenant, Tenant.id == AuditLog.tenant_id)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .where(*filters)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(list_stmt)).all()
        items = [
            AuditLogRow(
                id=r.id,
                tenant_id=r.tenant_id,
                tenant_name=r.name,
                actor_user_id=r.actor_user_id,
                actor_email=r.email,
                action=r.action,
                resource_type=r.resource_type,
                resource_id=r.resource_id,
                ip_address=r.ip_address,
                created_at=r.created_at,
            )
            for r in rows
        ]
        return items, int(total)
