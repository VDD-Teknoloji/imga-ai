"""Geçerli ``primary_category`` kod kümesi — global + kurum-özel.

2026-08-18 WS2 adversarial inceleme bulgusu: üç ayrı kapı (drill-down
422'si, kök neden 422'si, taksonomi ``primary_category_code``
doğrulaması) yalnız ``GLOBAL_CATEGORY_CODES`` sabitine bakıyordu.
Kurum kendi custom ``Category`` satırını (WS1 — kuruma özel
kategoriler) açtığında bu üç kapı hâlâ onu reddediyordu; A-sistemi
kâğıt üstünde kalıyordu. Tek ortak yardımcı burada — üç kapı de aynı
kümeye bakar, birbirinden sapmaz.

Not: sınıflandırıcının ``available_categories`` kümesi (etkin
global + custom, ``tenant_categories.is_enabled`` toggle'ıyla)
bundan FARKLI bir kavram — bkz. ``batch_analyzer._load_tenant_
category_snapshot``. Bu modül yalnız "kod var mı, geçerli mi"
doğrulaması yapar; toggle durumuna bakmaz (kapatılmış bir global kod
hâlâ geçerli bir koddur, sadece sınıflandırıcı ona düşmez — eski
satırlar eski kodlarını korur, drill-down'da hâlâ görünür olmalı).
"""

from __future__ import annotations

from uuid import UUID

from imga_core.categories.taxonomy import GLOBAL_CATEGORY_CODES
from imga_db.models import Category
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def valid_primary_codes(session: AsyncSession, tenant_id: UUID) -> set[str]:
    """``GLOBAL_CATEGORY_CODES`` + kurumun aktif (``deleted_at IS
    NULL``) custom ``Category`` kodları.

    RLS altında (app session) zaten yalnız global + kendi custom
    satırlarını görür; ``tenant_id ==`` filtresi yine de açık —
    admin/bypass session'dan çağrılırsa (örn. testler) başka kurumun
    custom kodu sızmasın diye (tenant_taxonomies.py'deki mevcut
    "belt-and-braces" kuralıyla aynı gerekçe).
    """
    rows = (
        await session.execute(
            select(Category.code)
            .where(Category.tenant_id == tenant_id)
            .where(Category.deleted_at.is_(None))
        )
    ).scalars().all()
    return set(GLOBAL_CATEGORY_CODES) | {str(code) for code in rows}


__all__ = ["valid_primary_codes"]
