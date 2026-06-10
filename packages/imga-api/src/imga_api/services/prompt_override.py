"""Sprint 11.3 — prompt seçim yardımcısı: DB override > kod varsayılanı.

Sprint 9.3 D'de gelen PromptResolver altyapısı bu sprint'e kadar
hiçbir LLM çağrı noktasına bağlanmamıştı — tenant bir şablonu
düzenlese bile üretim kod sabitleriyle akıyordu. Bu modül üç üretim
servisi (SWOT/OKR/briefing) için tek tip köprü:

  1. ``prompt_templates``'ta tenant override ya da global default
     varsa → onu Jinja ile render et, kullan.
  2. Yoksa (PromptTemplateNotFound) → kod sabitleri (bugünkü
     davranış, güvenlik ağı).
  3. Override VAR ama render PATLARSA (eksik değişken, bozuk Jinja)
     → logla ve kod varsayılanına düş — kullanıcı şablonu bozdu
     diye SWOT üretimi 500 atmaz.

``source`` audit'e akar: rapor hangi prompt'la üretildi sorusunun
cevabı ("tenant_override" | "global_default" | "code_default").
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.prompt_resolver import (
    PromptResolver,
    PromptResolverError,
    PromptTemplateNotFound,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PromptSelection:
    system_prompt: str
    user_prompt: str
    source: str  # "tenant_override" | "global_default" | "code_default"
    version: str


async def select_prompt(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    template_key: str,
    variables: dict[str, Any],
    default_system_prompt: str,
    default_user_prompt: Callable[[], str],
) -> PromptSelection:
    """DB-öncelikli prompt seçimi. ``default_user_prompt`` lazy —
    override başarılıysa kod şablonu hiç render edilmez."""
    try:
        resolved = await PromptResolver(session).render(
            template_key=template_key,
            tenant_id=tenant_id,
            variables=variables,
        )
        return PromptSelection(
            system_prompt=resolved.system_prompt,
            user_prompt=resolved.user_prompt_rendered,
            source=resolved.source,
            version=resolved.version,
        )
    except PromptTemplateNotFound:
        pass
    except PromptResolverError as exc:
        logger.warning(
            "prompt override render failed for key=%s tenant=%s; "
            "falling back to code default: %s",
            template_key,
            tenant_id,
            exc,
        )
    return PromptSelection(
        system_prompt=default_system_prompt,
        user_prompt=default_user_prompt(),
        source="code_default",
        version="v1",
    )
