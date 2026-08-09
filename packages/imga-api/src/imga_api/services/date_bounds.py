"""Gün-hassasiyetli tarih filtreleri için TIMESTAMPTZ sınırları.

``Review.created_at <= <date>`` deseni Postgres'te tarihi GECEYARISINA
çevirir — bitiş günü (ör. "bugün") pencereden düşer. Snapshot servisi
bunu Sprint 9.4 C'de yerinde çözmüştü; 2026-08-09 vakası (bugün analiz
edilen 9903 yorumun Yönetici Özeti'nde görünmemesi) aynı hatanın
brifing/cohort/heatmap/kelime-bulutu kopyalarını ortaya çıkardı — artık
tek yardımcı: alt sınır gün başı, üst sınır gün sonu.
"""

from __future__ import annotations

from datetime import UTC, date, datetime


def day_floor(d: date) -> datetime:
    """Günün başı (00:00:00.000000, UTC)."""
    return datetime.combine(d, datetime.min.time(), tzinfo=UTC)


def day_ceil(d: date) -> datetime:
    """Günün sonu (23:59:59.999999, UTC) — bitiş gününü tam kapsar."""
    return datetime.combine(d, datetime.max.time(), tzinfo=UTC)
