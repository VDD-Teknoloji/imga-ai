"""PromptTemplate model — system-level prompt + schema registry.

Sprint 8.3.6 / Alt-Faz 8.3.6.1.F. One row per ``template_key`` (e.g.
``"swot_v1"``, ``"okr_v1"``). System-level — no RLS, every tenant
shares the same templates. Tenant-specific overrides land in a future
sprint.

Real prompts + finalised response schemas land in Sprint 8.3.6.3
(SWOT) / 8.3.6.4 (OKR) via in-place ``UPDATE``; migration 0019 ships
placeholder rows so the SWOT/OKR generator service has something to
look up before that work merges.

``temperature`` / ``top_p`` / ``max_output_tokens`` are knobs the
service applies to the Gemini SDK call. Defaults match the design
review's "deterministic-ish but not robotic" target.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    template_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )

    system_prompt: Mapped[str] = mapped_column(Text(), nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text(), nullable=False)
    response_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), nullable=False
    )

    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    temperature: Mapped[float] = mapped_column(Float(), nullable=False, default=0.2)
    top_p: Mapped[float] = mapped_column(Float(), nullable=False, default=0.9)
    max_output_tokens: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=8192
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
