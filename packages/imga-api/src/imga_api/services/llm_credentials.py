"""Shared LLM-credential helpers for SWOT + OKR generators.

Sprint 8.3.6 / Alt-Faz 8.3.6.4. Split out from swot_service.py so the
OKR service can reuse the load + mark-failed paths without an
unsightly cross-service import. The functions stay async because they
hit the bound RLS session; ``NoCredentialsError`` lives here too so
both services raise the same class.

Backward compatibility: ``swot_service.NoCredentialsError`` re-exports
this class so existing imports + tests keep working unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from imga_core.llm import GeminiKey
from imga_core.security.encryption import EncryptionError, decrypt
from imga_db.models import TenantLlmCredential
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)


class NoCredentialsError(Exception):
    """Tenant has no active LLM credential rows. Surfaces as 412
    Precondition Failed; frontend redirects to /settings/integrations."""


@dataclass(frozen=True, slots=True)
class LlmKeySelection:
    """Kurumun kazanan LLM yapılandırması.

    Kural: en yüksek öncelikli (priority=0'a en yakın) AKTİF kimlik
    kaydının sağlayıcısı kazanır; rotasyon listesi yalnız o sağlayıcının
    aktif anahtarlarından kurulur. ``model`` kazanan satırın model
    seçimi (NULL → sağlayıcı varsayılanı). Böylece Gemini'den
    OpenRouter'a geçiş, seçicide OpenRouter satırını en üste taşımaktan
    ibarettir — eski kayıtları silmek gerekmez.
    """

    provider: str
    model: str | None
    keys: list[GeminiKey]


async def load_active_gemini_keys(
    session: AsyncSession, tenant_id: UUID
) -> list[GeminiKey]:
    """Load + decrypt the tenant's active Gemini credentials in
    priority order (0 = primary). Decryption failures (master key
    mismatch, corrupt ciphertext) skip the row with a warning rather
    than abort the whole rotation — a single bad credential shouldn't
    take down a tenant's other working keys.

    Returned list is safe to feed to ``GeminiKeyRotator``.
    """
    stmt = (
        select(TenantLlmCredential)
        .where(TenantLlmCredential.tenant_id == tenant_id)
        .where(TenantLlmCredential.provider == "gemini")
        .where(TenantLlmCredential.is_active.is_(True))
        .order_by(TenantLlmCredential.priority.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    out: list[GeminiKey] = []
    for row in rows:
        try:
            plaintext = decrypt(row.encrypted_value)
        except EncryptionError as exc:
            _logger.warning(
                "llm_credentials: skipping credential id=%s — decrypt failed (%s)",
                row.id, exc,
            )
            continue
        out.append(
            GeminiKey(
                id=str(row.id),
                value=plaintext,
                label=row.label,
                priority=row.priority,
            )
        )
    return out


async def load_active_llm_keys(
    session: AsyncSession, tenant_id: UUID
) -> LlmKeySelection | None:
    """Sağlayıcı-farkındalıklı yükleyici: SWOT/OKR/brifing + batch
    sınıflandırma yolları bunu kullanır. En yüksek öncelikli aktif
    satırın sağlayıcısı kazanır (bkz. LlmKeySelection docstring).

    ``load_active_gemini_keys`` embedding yolu için ayrı yaşamaya devam
    eder — embedding API'si Gemini'ye özgü, kazanan sağlayıcı OpenRouter
    olsa bile embedding'ler Gemini anahtarı ister.

    None → hiç aktif kimlik yok (çağıran keyword-only'e düşer veya
    NoCredentialsError yükseltir).
    """
    stmt = (
        select(TenantLlmCredential)
        .where(TenantLlmCredential.tenant_id == tenant_id)
        .where(TenantLlmCredential.is_active.is_(True))
        # created_at ikincil sıralama: eski (yalnız-Gemini dönemi)
        # verisinde iki sağlayıcı aynı önceliği paylaşabilir; kazanan
        # deterministik kalsın.
        .order_by(
            TenantLlmCredential.priority.asc(),
            TenantLlmCredential.created_at.asc(),
        )
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return None
    winning_provider = rows[0].provider
    winning_model = rows[0].model
    keys: list[GeminiKey] = []
    for row in rows:
        if row.provider != winning_provider:
            continue
        try:
            plaintext = decrypt(row.encrypted_value)
        except EncryptionError as exc:
            _logger.warning(
                "llm_credentials: skipping credential id=%s — decrypt failed (%s)",
                row.id, exc,
            )
            continue
        keys.append(
            GeminiKey(
                id=str(row.id),
                value=plaintext,
                label=row.label,
                priority=row.priority,
            )
        )
    if not keys:
        return None
    return LlmKeySelection(
        provider=winning_provider, model=winning_model, keys=keys
    )


async def mark_keys_failed(
    session: AsyncSession, key_ids: list[UUID]
) -> None:
    """Stamp ``last_failed_at`` on the given credential rows. Used for
    keys that hit InvalidKeyError (not transient rate-limits). The
    /settings/integrations UI reads this column to surface "needs
    attention". Empty list is a no-op."""
    if not key_ids:
        return
    await session.execute(
        update(TenantLlmCredential)
        .where(TenantLlmCredential.id.in_(key_ids))
        .values(last_failed_at=datetime.now(UTC))
    )
