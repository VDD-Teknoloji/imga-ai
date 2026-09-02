"""Tek seferlik KVKK geri doldurma — kalıcı kök neden payload'larındaki
e-posta / telefon / TCKN / IBAN / ad kalıplarını maskeler (2026-09-02).

Neden: services/pii_mask.py ve prompt kuralı 12'den ÖNCE üretilmiş
analizlerin alıntıları ham yorumdan kişisel veri taşıyor. Kişi adlarının
tamamı deterministik yakalanamaz; görüntülenen (kart başına en taze)
analizler ayrıca yeniden üretilir, bu betik geri kalan tarihçeyi ve
modelin kaçırdığı e-posta/telefonu temizler.

Çalıştırma (api konteyneri içinde, RLS'siz yönetici bağlantısıyla):

    sudo docker compose -f $COMPOSE exec -T api \\
        python -m imga_api.scripts_mask_root_cause  # (bkz. aşağıdaki heredoc)

Bu dosya repoda referans olarak durur; sunucuda ``python - < dosya``
ile stdin'den de çalıştırılabilir. İdempotent: ikinci koşu 0 satır
günceller.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from imga_db import create_engine, create_session_factory
from imga_db.models import RootCauseAnalysis
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from imga_api.services.pii_mask import mask_pii

_TEXT_FIELDS = (
    "title",
    "description",
    "affected_surface",
    "suggested_action",
    "headline",
    "action_short",
    "expert_note",
)


def _mask_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    summary = payload.get("summary")
    if isinstance(summary, str):
        masked = mask_pii(summary)
        if masked != summary:
            payload["summary"] = masked
            changed = True
    causes = payload.get("root_causes")
    if isinstance(causes, list):
        for cause in causes:
            if not isinstance(cause, dict):
                continue
            for field in _TEXT_FIELDS:
                value = cause.get(field)
                if isinstance(value, str):
                    masked = mask_pii(value)
                    if masked != value:
                        cause[field] = masked
                        changed = True
            quotes = cause.get("evidence_quotes")
            if isinstance(quotes, list):
                new_quotes = [mask_pii(q) if isinstance(q, str) else q for q in quotes]
                if new_quotes != quotes:
                    cause["evidence_quotes"] = new_quotes
                    changed = True
    return payload, changed


async def main() -> None:
    if not os.environ.get("DATABASE_URL_ADMIN"):
        raise SystemExit("DATABASE_URL_ADMIN gerekli (RLS'siz yönetici bağlantısı)")
    engine = create_engine("admin")
    factory = create_session_factory(engine)
    scanned = updated = 0
    async with factory() as session, session.begin():
        rows = (await session.execute(select(RootCauseAnalysis))).scalars().all()
        for row in rows:
            scanned += 1
            payload = row.payload if isinstance(row.payload, dict) else None
            if payload is None:
                continue
            _, changed = _mask_payload(payload)
            if changed:
                flag_modified(row, "payload")
                updated += 1
    await engine.dispose()
    print(f"scanned={scanned} updated={updated}")


if __name__ == "__main__":
    asyncio.run(main())
