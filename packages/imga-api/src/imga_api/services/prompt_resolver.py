"""Sprint 9.3 D — tenant-aware prompt template resolver.

The platform's LLM call sites used to embed prompts as Python
constants; Sprint 9.3 D moves the active version into the
``prompt_templates`` table so a tenant admin can override a global
template without a code deploy. The resolver walks the priority
chain:

  1. Tenant override default — ``tenant_id == tenant``,
     ``is_default = TRUE``, ``is_active = TRUE``.
  2. Tenant override explicit version — ``tenant_id == tenant`` +
     a specific ``version`` the caller asks for.
  3. Global default — ``tenant_id IS NULL``, ``is_default = TRUE``,
     ``is_active = TRUE``.
  4. ``None`` — caller's responsibility to fall back to a
     hard-coded constant (the safety net the classifier ships).

Stays a pure dispatcher over a session: the caller wraps it in
their own ``async with session.begin():``. The resolver does NOT
manage transactions or set the RLS tenant context — that's the
route layer's job.

Jinja2 rendering is a separate concern; this module returns the
``PromptTemplate`` row and lets the caller render. The render
helper at the bottom is a convenience wrapper for the common
``resolve + render`` flow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from imga_db.models import PromptTemplate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)


class PromptResolverError(Exception):
    """Service-layer failure that maps to a 4xx in routes."""


class PromptTemplateNotFound(PromptResolverError):
    """No row matched the requested key (tenant override + global
    are both missing). Caller should fall back to a hard-coded
    constant, not 500."""


class MissingRequiredVariable(PromptResolverError):
    """The render call left a ``required_variables`` slot empty."""


@dataclass(frozen=True, slots=True)
class ResolvedPrompt:
    """The shape every caller sees regardless of which row served
    the resolution. The ``source`` field tells the audit log
    whether this was a tenant override or the global default."""

    template_key: str
    version: str
    system_prompt: str
    user_prompt_rendered: str
    response_schema: dict[str, Any]
    model_name: str
    temperature: float
    top_p: float
    max_output_tokens: int
    source: str  # "tenant_override" | "global_default"


class PromptResolver:
    """Session-bound resolver. The caller passes a session that's
    already bound to the active tenant context (RLS); the resolver
    queries ``prompt_templates`` via that session and returns the
    highest-priority row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve_template(
        self,
        *,
        template_key: str,
        tenant_id: UUID,
        version: str | None = None,
    ) -> PromptTemplate | None:
        """Walk the priority chain. Returns ``None`` when nothing
        matches — caller decides whether to 404, fall back, or
        raise."""
        # 1. Tenant override (default or explicit version).
        tenant_stmt = select(PromptTemplate).where(
            PromptTemplate.template_key == template_key,
            PromptTemplate.tenant_id == tenant_id,
            PromptTemplate.is_active.is_(True),
        )
        if version is None:
            tenant_stmt = tenant_stmt.where(
                PromptTemplate.is_default.is_(True)
            )
        else:
            tenant_stmt = tenant_stmt.where(
                PromptTemplate.version == version
            )
        tenant_row = (
            await self._session.execute(tenant_stmt)
        ).scalar_one_or_none()
        if tenant_row is not None:
            return tenant_row

        # 2. Global default (or explicit version).
        global_stmt = select(PromptTemplate).where(
            PromptTemplate.template_key == template_key,
            PromptTemplate.tenant_id.is_(None),
            PromptTemplate.is_active.is_(True),
        )
        if version is None:
            global_stmt = global_stmt.where(
                PromptTemplate.is_default.is_(True)
            )
        else:
            global_stmt = global_stmt.where(
                PromptTemplate.version == version
            )
        global_row = (
            await self._session.execute(global_stmt)
        ).scalar_one_or_none()
        return global_row

    async def render(
        self,
        *,
        template_key: str,
        tenant_id: UUID,
        variables: dict[str, Any],
        version: str | None = None,
    ) -> ResolvedPrompt:
        """Resolve + Jinja2 render in one call. Raises
        ``PromptTemplateNotFound`` if neither tenant nor global has
        a row, ``MissingRequiredVariable`` if the prompt template
        declares a variable the caller didn't pass."""
        row = await self.resolve_template(
            template_key=template_key,
            tenant_id=tenant_id,
            version=version,
        )
        if row is None:
            raise PromptTemplateNotFound(
                f"no prompt template registered for key={template_key!r} "
                f"(neither tenant override nor global default)"
            )
        return _render_row(row, variables=variables)


def _render_row(
    row: PromptTemplate,
    *,
    variables: dict[str, Any],
) -> ResolvedPrompt:
    """Pure rendering — extracted so tests can call it without a
    session. Jinja2 import is lazy so a future hot path that wants
    to skip rendering (raw template inspection) doesn't pay the
    sandbox-environment cost."""
    from jinja2 import Environment, StrictUndefined, TemplateError

    missing = [v for v in (row.required_variables or []) if v not in variables]
    if missing:
        raise MissingRequiredVariable(
            f"template {row.template_key}@{row.version} requires variables "
            f"{sorted(missing)} not supplied by caller"
        )
    env = Environment(undefined=StrictUndefined, autoescape=False)
    try:
        rendered = env.from_string(row.user_prompt_template).render(**variables)
    except TemplateError as exc:
        raise PromptResolverError(
            f"template render failed for {row.template_key}@{row.version}: {exc}"
        ) from exc
    source = "tenant_override" if row.tenant_id is not None else "global_default"
    return ResolvedPrompt(
        template_key=row.template_key,
        version=row.version,
        system_prompt=row.system_prompt,
        user_prompt_rendered=rendered,
        response_schema=dict(row.response_schema or {}),
        model_name=row.model_name,
        temperature=row.temperature,
        top_p=row.top_p,
        max_output_tokens=row.max_output_tokens,
        source=source,
    )


__all__ = [
    "MissingRequiredVariable",
    "PromptResolver",
    "PromptResolverError",
    "PromptTemplateNotFound",
    "ResolvedPrompt",
]
