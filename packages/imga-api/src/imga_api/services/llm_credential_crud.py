"""Ortak LLM-kimlik yuzeyleri: wire semasi, onizleme + model katalogu.

2026-08-09 — model / API anahtari yonetimi kurumdan super-admin'e
tasindi. Bu modul iki router'in paylastigi parcalari tutar:

  * ``routes/tenant_llm_credentials.py`` — salt-okur liste + katalog
  * ``routes/admin/llm_credentials.py``  — super-admin CRUD

Guvenlik sozlesmesi degismedi: duz metin anahtar yalniz create istek
govdesinde yasar, DB'de Fernet ciphertext durur ve her yanit sadece
``value_preview`` (son 4 karakter) tasir.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

import httpx
from imga_core.security.encryption import EncryptionError, decrypt
from imga_db.models import TenantLlmCredential
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- wire semasi ---------------------------------------------------


class CredentialResponse(BaseModel):
    id: UUID
    label: str
    provider: str
    model: str | None
    priority: int
    is_active: bool
    value_preview: str
    last_failed_at: datetime | None
    created_at: datetime
    updated_at: datetime


def value_preview(plaintext: str) -> str:
    """Last 4 chars of the API key, prefixed with ``...``. Enough for
    recognition, useless as a credential."""
    if len(plaintext) <= 4:
        return "..."
    return f"...{plaintext[-4:]}"


def to_response(
    row: TenantLlmCredential, *, plaintext: str | None = None
) -> CredentialResponse:
    """Materialise a credential row as the wire response. ``plaintext``
    is the just-decrypted value when the caller has it on hand
    (e.g. right after create); when ``None``, decryption is attempted
    here and a placeholder preview surfaces on failure (corrupted
    ciphertext / master key mismatch).
    """
    if plaintext is None:
        try:
            plaintext = decrypt(row.encrypted_value)
            preview = value_preview(plaintext)
        except EncryptionError:
            preview = "...?"
    else:
        preview = value_preview(plaintext)
    return CredentialResponse(
        id=row.id,
        label=row.label,
        provider=row.provider,
        model=row.model,
        priority=row.priority,
        is_active=row.is_active,
        value_preview=preview,
        last_failed_at=row.last_failed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_credential_rows(
    session: AsyncSession, tenant_id: UUID
) -> list[TenantLlmCredential]:
    """Priority-ordered credential rows for one kurum. The explicit
    ``tenant_id ==`` predicate is load-bearing on the admin session —
    imga_admin is BYPASSRLS, so nothing else scopes the query."""
    rows = (
        await session.execute(
            select(TenantLlmCredential)
            .where(TenantLlmCredential.tenant_id == tenant_id)
            .order_by(
                TenantLlmCredential.priority.asc(),
                TenantLlmCredential.created_at.asc(),
            )
        )
    ).scalars().all()
    return list(rows)


# --- OpenRouter model katalogu -------------------------------------
#
# Canli katalog proxy'si: model secicisi buradan beslenir, boylece
# yeni bir model ciktiginda kod degisikligi gerekmez. 1 saatlik surec-
# ici onbellek; katalog erisilemezse bayat kopya, o da yoksa kuratorlu
# liste kimlik-only doner (secici asla bos kalmaz).

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_CATALOG_TTL_SECONDS = 3600.0

# Kuratorlu onerilenler — secicide en ustte gorunur. 2026-08 canli
# katalogdan dogrulanan, yapisal cikti destekli secki.
CURATED_OPENROUTER_MODELS: tuple[str, ...] = (
    # 2026-08-10 Navlungo benchmark birincisi — sistem varsayilani.
    "z-ai/glm-5.2",
    "openai/gpt-5-mini",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-pro",
    "google/gemini-3.6-flash",
    "google/gemini-3.5-flash-lite",
    "openai/gpt-5.6-terra",
    "openai/gpt-5.6-luna",
    "anthropic/claude-opus-5",
    "qwen/qwen3.8-max",
    "x-ai/grok-4.5",
    "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v4-flash-0731",
    "moonshotai/kimi-k3",
    "mistralai/mistral-large-2512",
    "meta-llama/llama-4-maverick",
    "z-ai/glm-5",
    "minimax/minimax-m2",
    "openai/gpt-5-nano",
)


class OpenRouterModelInfo(BaseModel):
    id: str
    name: str
    context_length: int | None
    # USD / 1M token (okunur birim; katalog token-basi dondurur).
    prompt_price_per_million: float | None
    completion_price_per_million: float | None
    structured_outputs: bool
    recommended: bool


class OpenRouterModelListResponse(BaseModel):
    models: list[OpenRouterModelInfo]
    # true -> canli katalog; false -> bayat/kuratorlu yedek.
    live: bool


_catalog_cache_models: list[OpenRouterModelInfo] | None = None
_catalog_cache_at: float = 0.0


def _parse_catalog(payload: dict[str, object]) -> list[OpenRouterModelInfo]:
    curated = set(CURATED_OPENROUTER_MODELS)
    out: list[OpenRouterModelInfo] = []
    data = payload.get("data")
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "")
        if not model_id:
            continue
        pricing = item.get("pricing")
        prompt_price: float | None = None
        completion_price: float | None = None
        if isinstance(pricing, dict):
            try:
                prompt_price = float(pricing.get("prompt") or 0) * 1_000_000
                completion_price = (
                    float(pricing.get("completion") or 0) * 1_000_000
                )
            except (TypeError, ValueError):
                prompt_price = completion_price = None
        supported = item.get("supported_parameters")
        structured = isinstance(supported, list) and (
            "structured_outputs" in supported
        )
        ctx = item.get("context_length")
        out.append(
            OpenRouterModelInfo(
                id=model_id,
                name=str(item.get("name") or model_id),
                context_length=int(ctx) if isinstance(ctx, int) else None,
                prompt_price_per_million=prompt_price,
                completion_price_per_million=completion_price,
                structured_outputs=structured,
                recommended=model_id in curated,
            )
        )
    # Onerilenler ustte (kurator sirasiyla), kalani ada gore.
    curated_order = {m: i for i, m in enumerate(CURATED_OPENROUTER_MODELS)}
    out.sort(
        key=lambda m: (
            0 if m.recommended else 1,
            curated_order.get(m.id, 0),
            m.id,
        )
    )
    return out


def _curated_fallback() -> list[OpenRouterModelInfo]:
    return [
        OpenRouterModelInfo(
            id=model_id,
            name=model_id,
            context_length=None,
            prompt_price_per_million=None,
            completion_price_per_million=None,
            structured_outputs=True,
            recommended=True,
        )
        for model_id in CURATED_OPENROUTER_MODELS
    ]


async def fetch_openrouter_catalog() -> OpenRouterModelListResponse:
    """1 saatlik surec-ici onbellekli katalog. Ag hatasi asla 500'e
    donusmez — bayat kopya, o da yoksa kuratorlu yedek doner."""
    global _catalog_cache_models, _catalog_cache_at

    now = time.monotonic()
    if (
        _catalog_cache_models is not None
        and (now - _catalog_cache_at) < _CATALOG_TTL_SECONDS
    ):
        return OpenRouterModelListResponse(
            models=_catalog_cache_models, live=True
        )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(OPENROUTER_MODELS_URL)
            resp.raise_for_status()
            models = _parse_catalog(resp.json())
        if models:
            _catalog_cache_models = models
            _catalog_cache_at = now
            return OpenRouterModelListResponse(models=models, live=True)
    except Exception:
        # Katalog best-effort — bayat kopyaya / kuratorlu yedege dusulur.
        pass
    if _catalog_cache_models is not None:
        return OpenRouterModelListResponse(
            models=_catalog_cache_models, live=False
        )
    return OpenRouterModelListResponse(models=_curated_fallback(), live=False)
