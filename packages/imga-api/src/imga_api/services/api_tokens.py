"""ApiTokenService — İmga v1 partner API token yaşam döngüsü (contract §8/§4A).

``api_tokens`` (kiracı Bearer, scope=tenant) + ``admin_tokens`` (opsBearer,
scope=ops) üzerinde mint / verify / rotate / revoke / list / mark_used.

Opak token üretimi + HMAC-SHA256(pepper) hashing ``security.api_tokens``'de;
bu servis DB orkestrasyonu + yaşam-döngüsü kuralları (TTL ≤ 1 yıl, revoke,
rotate overlap grace).

**verify() BYPASSRLS lookup:** auth sıcak yolunda henüz tenant bağlamı YOK;
lookup ``imga_admin`` (BYPASSRLS) session ile yapılır (api_tokens'ın RLS'i
tenant-scoped, admin_tokens deny-all — ikisi de yalnız BYPASSRLS ile okunur).
Tenant RLS'i middleware tarafından SONRA bağlanır (design §4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imga_db.models import AdminTokenRecord, ApiTokenRecord

from imga_api.security.api_tokens import (
    OPS_LIVE_PREFIX,
    OPS_STG_PREFIX,
    TENANT_LIVE_PREFIX,
    TENANT_STG_PREFIX,
    extract_prefix,
    hash_token,
    is_ops_prefix,
    mint_token,
)

# TTL tavanı: ölümsüz makine anahtarı yok (contract §4A.5 "1 yıl max").
MAX_TTL_DAYS = 365
DEFAULT_TTL_DAYS = 90
# §8.5 normative: revoke → ≤60 sn propagation.
REVOKE_PROPAGATION_SECONDS = 60

TokenRow = ApiTokenRecord | AdminTokenRecord


class TokenServiceError(Exception):
    """Yaşam-döngüsü kural ihlali (geçersiz scope/tenant/ttl)."""


@dataclass(frozen=True, slots=True)
class MintResult:
    """mint()/rotate() çıktısı. ``plaintext`` YALNIZ burada döner."""

    token_id: UUID
    plaintext: str
    token_prefix: str
    last4: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RotateResult:
    new: MintResult
    old_token_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class RevokeResult:
    revoked_at: datetime
    propagation_deadline: datetime


def _prefix_for(environment: str, *, ops: bool) -> str:
    """Ortam + scope → Stripe-style önek. production→live, aksi→stg (§8.1)."""
    live = environment == "production"
    if ops:
        return OPS_LIVE_PREFIX if live else OPS_STG_PREFIX
    return TENANT_LIVE_PREFIX if live else TENANT_STG_PREFIX


class ApiTokenService:
    """Stateless — her metoda AsyncSession + pepper geçilir."""

    def __init__(self, *, pepper: str, environment: str) -> None:
        if not pepper or len(pepper) < 32:
            # Fail-fast: partner API zayıf/boş pepper ile ÇALIŞMAZ (goal §3.1).
            raise TokenServiceError(
                "IMGA_TOKEN_PEPPER yapılandırılmamış veya < 32 karakter — "
                "partner API devre dışı."
            )
        self._pepper = pepper
        self._environment = environment

    # ---- mint --------------------------------------------------------
    async def mint(
        self,
        session: AsyncSession,
        *,
        scope: str,
        label: str,
        ttl_days: int = DEFAULT_TTL_DAYS,
        tenant_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> MintResult:
        if ttl_days < 1 or ttl_days > MAX_TTL_DAYS:
            raise TokenServiceError(f"ttl_days 1..{MAX_TTL_DAYS} olmalı")
        ops = scope == "ops"
        if ops and tenant_id is not None:
            raise TokenServiceError("ops token'ı tenant_id taşımaz (§8.6)")
        if not ops and (scope != "tenant" or tenant_id is None):
            raise TokenServiceError("tenant token'ı tenant_id + scope=tenant ister")

        prefix = _prefix_for(self._environment, ops=ops)
        minted = mint_token(prefix=prefix, pepper=self._pepper)
        expires_at = datetime.now(UTC) + timedelta(days=ttl_days)

        row: TokenRow
        if ops:
            row = AdminTokenRecord(
                token_prefix=minted.token_prefix,
                token_hash=minted.token_hash,
                last4=minted.last4,
                scope="ops",
                label=label,
                expires_at=expires_at,
            )
        else:
            row = ApiTokenRecord(
                tenant_id=tenant_id,
                token_prefix=minted.token_prefix,
                token_hash=minted.token_hash,
                last4=minted.last4,
                scope="tenant",
                label=label,
                created_by=created_by,
                expires_at=expires_at,
            )
        session.add(row)
        await session.flush()
        return MintResult(
            token_id=row.id,
            plaintext=minted.plaintext,  # <-- plaintext yalnız burada
            token_prefix=minted.token_prefix,
            last4=minted.last4,
            expires_at=expires_at,
        )

    # ---- verify (auth sıcak yolu, BYPASSRLS session) -----------------
    async def verify(
        self, session: AsyncSession, plaintext: str
    ) -> TokenRow | None:
        """Aktif token satırını döndür ya da None (yok/revoked/expired/önek
        tanınmaz). ``session`` BYPASSRLS (imga_admin) olmalı."""
        prefix = extract_prefix(plaintext)
        if prefix is None:
            return None
        token_hash = hash_token(plaintext, self._pepper)
        model: type[TokenRow] = (
            AdminTokenRecord if is_ops_prefix(prefix) else ApiTokenRecord
        )
        row = (
            await session.execute(
                select(model).where(model.token_hash == token_hash)
            )
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return None
        if row.expires_at <= datetime.now(UTC):
            return None
        return row

    # ---- rotate (§4A.3) ----------------------------------------------
    async def rotate(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        label: str,
        overlap_hours: int = 24,
        created_by: UUID | None = None,
    ) -> RotateResult:
        """Yeni tenant token üret; mevcut aktif token(ler)e ``overlap_hours``
        grace penceresi ver (expires_at'i now+overlap'e kısalt). AsakAI yeniye
        geçtikten sonra eski açıkça revoke edilir (contract §8.4)."""
        overlap_hours = max(1, min(overlap_hours, 72))  # §4A.3: max 72h
        new = await self.mint(
            session,
            scope="tenant",
            label=label,
            tenant_id=tenant_id,
            created_by=created_by,
        )
        grace_expiry = datetime.now(UTC) + timedelta(hours=overlap_hours)
        # Yeni token hariç, aktif eski tenant token'larını grace'e kısalt.
        result = await session.execute(
            update(ApiTokenRecord)
            .where(ApiTokenRecord.tenant_id == tenant_id)
            .where(ApiTokenRecord.id != new.token_id)
            .where(ApiTokenRecord.revoked_at.is_(None))
            .where(ApiTokenRecord.expires_at > grace_expiry)
            .values(expires_at=grace_expiry)
            .returning(ApiTokenRecord.id)
        )
        old_expiry = grace_expiry if result.first() is not None else None
        return RotateResult(new=new, old_token_expires_at=old_expiry)

    # ---- revoke (§4A.4 / §8.5) ---------------------------------------
    async def revoke(
        self, session: AsyncSession, token_id: UUID, *, reason: str | None = None
    ) -> RevokeResult | None:
        """Token'ı iptal et (api_tokens veya admin_tokens). ≤60s propagation
        deadline döner. Bulunamazsa None."""
        now = datetime.now(UTC)
        for model in (ApiTokenRecord, AdminTokenRecord):
            res = await session.execute(
                update(model)
                .where(model.id == token_id)
                .where(model.revoked_at.is_(None))
                .values(revoked_at=now, revoke_reason=reason)
                .returning(model.id)
            )
            if res.first() is not None:
                return RevokeResult(
                    revoked_at=now,
                    propagation_deadline=now
                    + timedelta(seconds=REVOKE_PROPAGATION_SECONDS),
                )
        return None

    # ---- list (§4A.5) ------------------------------------------------
    async def list_tenant_tokens(
        self, session: AsyncSession, tenant_id: UUID
    ) -> list[ApiTokenRecord]:
        """Kiracının aktif (revoke edilmemiş) token'ları — hash gösterilmez."""
        rows = (
            await session.execute(
                select(ApiTokenRecord)
                .where(ApiTokenRecord.tenant_id == tenant_id)
                .where(ApiTokenRecord.revoked_at.is_(None))
                .order_by(ApiTokenRecord.created_at.desc())
            )
        ).scalars().all()
        return list(rows)

    # ---- mark_used (debounce middleware'de) --------------------------
    async def mark_used(
        self, session: AsyncSession, row: TokenRow
    ) -> None:
        """last_used_at güncelle. Debounce (yalnız >60s'de bir yaz) çağıran
        middleware'de — burada koşulsuz set. Gözlem içindir, auth'a bağlı değil."""
        await session.execute(
            update(type(row))
            .where(type(row).id == row.id)
            .values(last_used_at=datetime.now(UTC))
        )


__all__ = [
    "ApiTokenService",
    "TokenServiceError",
    "MintResult",
    "RotateResult",
    "RevokeResult",
    "MAX_TTL_DAYS",
    "DEFAULT_TTL_DAYS",
    "REVOKE_PROPAGATION_SECONDS",
]
