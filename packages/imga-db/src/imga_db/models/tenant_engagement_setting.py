"""TenantEngagementSetting — katılım oranı değerlendirme bantları.

Bir kurumun "%2 katılım iyi mi kötü mü" sorusunun cevabı sektöre
göre değişir (perakende ile sigorta aynı eşiği paylaşmaz). Bu yüzden
bantlar kurum başına ve YALNIZCA süper yönetici tarafından
düzenlenir; kurum sadece işlem adedini girer.

``bands`` sıralı bir liste: ``[{"min_pct": 0, "label": "Çok Kötü"},
{"min_pct": 1, "label": "Kötü"}, ...]``. Bir bant kendi ``min_pct``
değerinden bir sonrakinin ``min_pct`` değerine kadar geçerlidir; eşiğin
tam üstündeki oran üst banda düşer. Şekil doğrulaması Pydantic'te
(artan/tekil min_pct, 1-8 bant, boş olmayan etiket) — JSONB tarafında
DB kısıtı yok, bilinçli: bant sayısı/etiketi ürün kararı, şema değil.

Satır yoksa servis katmanındaki varsayılan bantlar kullanılır; okuma
sırasında satır OLUŞTURULMAZ.

RLS+FORCE — bkz. migration 0039.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TenantEngagementSetting(Base):
    __tablename__ = "tenant_engagement_settings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", name="uq_tenant_engagement_settings_tenant"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    bands: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(), nullable=False, default=list
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
