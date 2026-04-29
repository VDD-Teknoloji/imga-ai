"""AuditService — append-only writes to audit_logs.

Every security-sensitive action (user create, invitation, role change,
tenant settings change, login attempt) goes through this service so the
caller doesn't need to remember the column layout.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from imga_db.models import AuditLog
from sqlalchemy.ext.asyncio import AsyncSession


class AuditService:
    """Append-only audit log writer.

    Reads happen elsewhere (RLS-scoped queries against audit_logs); this
    class is only for inserts. Audit logs are tenant-scoped when possible:
    a NULL tenant_id is reserved for super-admin / pre-tenant actions.
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
