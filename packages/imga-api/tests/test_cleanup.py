"""Unit tests for the daily upload-reaper.

Pure file IO — no DB. Verifies retention semantics + idempotency.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from imga_api.workers.cleanup import reap_stale_uploads


def _set_mtime(path: Path, hours_ago: float) -> None:
    """Backdate a file's mtime by ``hours_ago`` hours."""
    target = time.time() - (hours_ago * 3600)
    os.utime(path, (target, target))


def test_reaps_files_older_than_retention(tmp_path: Path) -> None:
    fresh = tmp_path / "tenant-a" / "job-1" / "fresh.csv"
    fresh.parent.mkdir(parents=True, exist_ok=True)
    fresh.write_bytes(b"text\nrow\n")

    stale = tmp_path / "tenant-b" / "job-2" / "stale.xlsx"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"binarystub")
    _set_mtime(stale, hours_ago=48)

    deleted = reap_stale_uploads(root=tmp_path, retention_hours=24)
    assert deleted == 1
    assert fresh.exists()
    assert not stale.exists()


def test_idempotent_when_no_stale_files(tmp_path: Path) -> None:
    (tmp_path / "tenant-a" / "job-1").mkdir(parents=True)
    (tmp_path / "tenant-a" / "job-1" / "f.csv").write_bytes(b"")
    deleted = reap_stale_uploads(root=tmp_path, retention_hours=24)
    assert deleted == 0


def test_missing_root_returns_zero(tmp_path: Path) -> None:
    deleted = reap_stale_uploads(
        root=tmp_path / "nonexistent", retention_hours=24
    )
    assert deleted == 0


def test_leaves_empty_directories_alone(tmp_path: Path) -> None:
    """Directories aren't collected — only files. Saves race-with-upload
    headaches when a fresh upload lands during cron."""
    empty = tmp_path / "tenant-a" / "job-empty"
    empty.mkdir(parents=True)
    deleted = reap_stale_uploads(root=tmp_path, retention_hours=24)
    assert deleted == 0
    assert empty.exists()
