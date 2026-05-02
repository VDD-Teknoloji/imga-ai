"""Daily cleanup cron — reap stale upload files under the batch upload
root.

Sprint 8.3.1 / decision 15: 24h retention. This worker iterates the
``upload_dir`` and deletes files (not the directory) older than
``retention_hours``. The ``analyze_batch_jobs.file_path`` column
deliberately survives — auditors still see WHERE a file lived even
after the bytes are gone.

The directory walk is deliberately lazy + idempotent: if a tenant
folder is empty, we leave it alone (cheap; saves cross-cron races
with the upload route writing into a fresh subdir).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger("imga-api.workers.cleanup")


def reap_stale_uploads(*, root: Path, retention_hours: int) -> int:
    """Walk ``root`` and unlink files older than retention. Returns the
    deletion count for log visibility / metric.

    Safe to call when ``root`` doesn't exist (returns 0). Errors on
    individual files are logged but don't abort the sweep — one
    locked / permission-denied file shouldn't strand the cron.
    """
    if not root.exists():
        return 0

    cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
    cutoff_ts = cutoff.timestamp()
    deleted = 0

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            log.warning("cleanup: stat failed for %s: %s", path, exc)
            continue
        if mtime >= cutoff_ts:
            continue
        try:
            path.unlink()
            deleted += 1
        except OSError as exc:
            log.warning("cleanup: unlink failed for %s: %s", path, exc)
    return deleted


__all__ = ["reap_stale_uploads"]
