"""Runtime configuration loaded from environment variables.

`.env` support: if a ``.env`` file exists in the current working
directory (where uvicorn is launched), each `KEY=value` line is loaded
into ``os.environ`` *without overriding* values already set by the
shell. ``.env.local`` takes precedence over ``.env`` for per-machine
overrides. Production deployments don't use either — env vars come
from the orchestrator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from imga_core.config import (
    DEFAULT_BERT_MODEL,
    DEFAULT_MAX_SHIPPING_DAYS,
    DEFAULT_MAX_WAREHOUSE_DAYS,
)


def _load_dotenv() -> None:
    """Load .env / .env.local from cwd into os.environ, shell wins."""
    cwd = Path.cwd()
    # .env.local first so its values populate os.environ before .env;
    # setdefault means a key already present (from shell or .env.local)
    # is never replaced by a later .env line.
    for candidate in (cwd / ".env.local", cwd / ".env"):
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            # Strip optional matching quotes around value, no escape parsing.
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)


@dataclass(frozen=True, slots=True)
class JWTSettings:
    """JWT signing + token lifetime configuration."""

    secret_key: str = "change-this-in-production-min-32-chars"
    algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7


@dataclass(frozen=True, slots=True)
class BatchSettings:
    """Sprint 8.3.1 bulk upload + worker configuration.

    ``upload_dir`` is where multipart payloads land before the worker
    streams them. Each tenant gets a subdir, each job gets its own
    sub-subdir. Production mounts /var/imga/uploads as a Docker volume;
    tests pass tmp_path through this setting so they don't need a
    privileged path.

    ``retention_hours`` drives the daily cleanup cron — files older
    than this are reaped, but the ``analyze_batch_jobs.file_path``
    column is preserved as audit trail.

    Concurrency limits are in-memory (asyncio Semaphore + per-tenant
    Lock). They assume a single API instance; multi-instance
    deployments need an advisory-lock variant in Sprint 9+.
    """

    upload_dir: Path = Path("/var/imga/uploads")
    max_file_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_rows: int = 10_000
    # Sprint 9.0.5-A R6 — was 1000; see from_env() comment.
    chunk_size: int = 200
    retention_hours: int = 24
    global_concurrency: int = 2  # server-wide simultaneous batch jobs
    per_tenant_concurrency: int = 1  # one batch per tenant at a time
    # Sprint 9.0.5-A R7 — bound on parallel LLM (Gemini) calls per
    # job. R7 dropped this 8 -> 4 as a defensive measure during the
    # 504-storm fix; py-spy validation post-deploy (Pattern A
    # confirmation) showed the SDK retry-disable + asyncio safety
    # net + mid-batch cancel are doing their job — fan-out can go
    # back to 8 without re-introducing the OOM regression. Paid
    # Gemini Tier 1 is 1000 RPM ≈ 16 RPS, so 8 in flight averages
    # ~8 RPS sustained — well under the ceiling and ~2× faster on
    # the 98-row demo. Worker passes this through to
    # HybridClassifier.
    llm_concurrency: int = 8


@dataclass(frozen=True, slots=True)
class ReportSettings:
    """Sprint 8.3.2 multi-sheet Excel/CSV export configuration.

    ``reports_dir`` mirrors uploads — same /var/imga mount but a
    separate top-level dir so disk-usage dashboards can split them
    cleanly. ``retention_hours`` (24h) drives both the file-reaper cron
    and the ``expires_at`` column on ``report_jobs``: download requests
    past that point return 410 Gone.

    Hard limits per Sprint 8.3.2 user decision 16:
      * date span: max 90 days
      * row count:  max 50,000
    """

    reports_dir: Path = Path("/var/imga/reports")
    retention_hours: int = 24
    max_days: int = 90
    max_rows: int = 50_000


@dataclass(frozen=True, slots=True)
class Settings:
    bert_model: str = DEFAULT_BERT_MODEL
    knowledge_base_path: Path | None = None
    rules_path: Path | None = None
    max_shipping_days: int = DEFAULT_MAX_SHIPPING_DAYS
    max_warehouse_days: int = DEFAULT_MAX_WAREHOUSE_DAYS
    jwt: JWTSettings = JWTSettings()
    batch: BatchSettings = BatchSettings()
    report: ReportSettings = ReportSettings()

    @classmethod
    def from_env(cls) -> Settings:
        _load_dotenv()

        def _opt_path(name: str) -> Path | None:
            raw = os.environ.get(name)
            return Path(raw) if raw else None

        def _int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            try:
                return int(raw) if raw else default
            except ValueError:
                return default

        jwt = JWTSettings(
            secret_key=os.environ.get(
                "JWT_SECRET_KEY",
                "change-this-in-production-min-32-chars",
            ),
            algorithm=os.environ.get("JWT_ALGORITHM", "HS256"),
            access_token_ttl_minutes=_int("JWT_ACCESS_TOKEN_TTL_MINUTES", 15),
            refresh_token_ttl_days=_int("JWT_REFRESH_TOKEN_TTL_DAYS", 7),
        )

        batch_upload_dir = os.environ.get("IMGA_UPLOAD_DIR")
        batch = BatchSettings(
            upload_dir=Path(batch_upload_dir) if batch_upload_dir else Path("/var/imga/uploads"),
            max_file_bytes=_int("IMGA_BATCH_MAX_FILE_BYTES", 50 * 1024 * 1024),
            max_rows=_int("IMGA_BATCH_MAX_ROWS", 10_000),
            # Sprint 9.0.5-A R6 — default 1000 -> 200. The earlier
            # default produced one chunk-end progress write every
            # ~9 minutes on a 2852-row LLM-bound run, leaving the
            # SSE / polling UI showing 0/2852 for the first commit
            # window. 200 commits every ~30s, so the demo's live
            # progress UI updates several times per minute. The
            # extra DB transactions per chunk are dwarfed by the
            # BERT + LLM time. Override via env when a deploy needs
            # different granularity.
            chunk_size=_int("IMGA_BATCH_CHUNK_SIZE", 200),
            retention_hours=_int("IMGA_BATCH_RETENTION_HOURS", 24),
            global_concurrency=_int("IMGA_BATCH_GLOBAL_CONCURRENCY", 2),
            per_tenant_concurrency=_int("IMGA_BATCH_PER_TENANT_CONCURRENCY", 1),
            llm_concurrency=_int("IMGA_BATCH_LLM_CONCURRENCY", 8),
        )

        reports_dir_env = os.environ.get("IMGA_REPORTS_DIR")
        report = ReportSettings(
            reports_dir=Path(reports_dir_env) if reports_dir_env else Path("/var/imga/reports"),
            retention_hours=_int("IMGA_REPORT_RETENTION_HOURS", 24),
            max_days=_int("IMGA_REPORT_MAX_DAYS", 90),
            max_rows=_int("IMGA_REPORT_MAX_ROWS", 50_000),
        )

        return cls(
            bert_model=os.environ.get("IMGA_BERT_MODEL", DEFAULT_BERT_MODEL),
            knowledge_base_path=_opt_path("IMGA_KB_PATH"),
            rules_path=_opt_path("IMGA_RULES_PATH"),
            max_shipping_days=_int("IMGA_MAX_SHIPPING_DAYS", DEFAULT_MAX_SHIPPING_DAYS),
            max_warehouse_days=_int("IMGA_MAX_WAREHOUSE_DAYS", DEFAULT_MAX_WAREHOUSE_DAYS),
            jwt=jwt,
            batch=batch,
            report=report,
        )
