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
class CookieSettings:
    """Sprint 9.0.6 B — HttpOnly auth-cookie configuration.

    The defaults are dev-safe: same-host, no Secure flag (so plain
    http://localhost works), SameSite=Lax. Production overrides via
    env: IMGA_COOKIE_SECURE=true + IMGA_COOKIE_DOMAIN=.imga.ai so the
    same cookie covers app.imga.ai + api.imga.ai (cross-subdomain
    same-site).

    ``access_name`` / ``refresh_name`` are kept distinct from common
    third-party names (no plain ``access_token``) so a future shared
    Caddy / proxy can't accidentally intercept or strip them.
    """

    access_name: str = "imga_access"
    refresh_name: str = "imga_refresh"
    secure: bool = False
    samesite: str = "lax"  # "lax" | "strict" | "none"
    domain: str | None = None
    path: str = "/"


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
    cookies: CookieSettings = CookieSettings()
    batch: BatchSettings = BatchSettings()
    report: ReportSettings = ReportSettings()
    # Sprint 9.0.6 D — gate the legacy public demo endpoints
    # (/analyze, /analyze/batch, /classify, /metrics) that pre-date
    # the tenant-scoped surface. Default false: production servers
    # 404 these paths so an unauthenticated probe can't burn BERT
    # inference. Flip to true only when an external integration
    # explicitly relies on the legacy contract.
    enable_public_demo_endpoints: bool = False
    # Sprint 9.7 — shared bearer for the imga.ai marketing site's
    # trial proxy (POST /public/trial/analyze). The marketing
    # backend signs server-to-server requests with this token; we
    # compare via hmac.compare_digest. None disables the endpoint
    # entirely (returns 503) so a misconfigured deploy can't accept
    # unauthenticated trial traffic. Min 32 chars enforced at load
    # time.
    imga_api_trial_key: str | None = None
    # Sprint 13 — İmga v1 partner API (AsakAI). ``token_pepper`` = HMAC-SHA256
    # pepper for opaque API-token at-rest hashing; prod + staging MUST differ
    # (32-byte, never committed). None → partner API disabled (the token
    # service fails fast on first use). ``environment`` (from IMGA_ENV) drives
    # the Stripe-style token prefix + cross-env enforcement:
    # production→imga_live_, everything else→imga_stg_.
    token_pepper: str | None = None
    environment: str = "development"

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

        cookie_samesite_raw = os.environ.get("IMGA_COOKIE_SAMESITE", "lax").lower()
        if cookie_samesite_raw not in ("lax", "strict", "none"):
            cookie_samesite_raw = "lax"
        # Sprint 9.1 I — production-aware default for cookie.secure.
        # 9.0.6 shipped with secure=False as the default which meant a
        # misconfigured production server would silently accept plain
        # HTTP and skip the Secure flag. We now flip the default based
        # on IMGA_ENV: ``production`` / ``staging`` defaults to True
        # (HTTPS-only), other values keep the dev-friendly False so
        # localhost still works without a TLS cert. Explicit
        # IMGA_COOKIE_SECURE always wins.
        env_name = os.environ.get("IMGA_ENV", "development").lower()
        cookie_secure_default = env_name in ("production", "staging")
        cookie_secure_raw = os.environ.get("IMGA_COOKIE_SECURE")
        cookie_secure = (
            cookie_secure_raw.lower() == "true"
            if cookie_secure_raw is not None
            else cookie_secure_default
        )
        cookies = CookieSettings(
            access_name=os.environ.get("IMGA_COOKIE_ACCESS_NAME", "imga_access"),
            refresh_name=os.environ.get("IMGA_COOKIE_REFRESH_NAME", "imga_refresh"),
            secure=cookie_secure,
            samesite=cookie_samesite_raw,
            domain=os.environ.get("IMGA_COOKIE_DOMAIN") or None,
            path=os.environ.get("IMGA_COOKIE_PATH", "/"),
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

        enable_public_demo_endpoints = (
            os.environ.get("IMGA_ENABLE_PUBLIC_DEMO_ENDPOINTS", "false").lower()
            == "true"
        )

        # Sprint 9.7 — trial proxy bearer. Refuse anything shorter
        # than 32 chars at load time; a too-short key in env is a
        # config bug, not a security exemption.
        trial_key_raw = os.environ.get("IMGA_API_TRIAL_KEY")
        if trial_key_raw is not None and len(trial_key_raw) < 32:
            raise ValueError(
                "IMGA_API_TRIAL_KEY must be at least 32 characters "
                "(set to a 64-byte hex via `python -c 'import secrets; "
                "print(secrets.token_hex(32))'`)"
            )

        # Sprint 13 — partner API token pepper. Same min-32 rule as the
        # trial key: a too-short pepper in env is a config bug, not an
        # exemption. None is allowed (partner API simply disabled).
        token_pepper_raw = os.environ.get("IMGA_TOKEN_PEPPER")
        if token_pepper_raw is not None and len(token_pepper_raw) < 32:
            raise ValueError(
                "IMGA_TOKEN_PEPPER must be at least 32 characters and "
                "distinct between prod and staging (generate via "
                "`python -c 'import secrets; print(secrets.token_hex(32))'`)"
            )

        return cls(
            bert_model=os.environ.get("IMGA_BERT_MODEL", DEFAULT_BERT_MODEL),
            knowledge_base_path=_opt_path("IMGA_KB_PATH"),
            rules_path=_opt_path("IMGA_RULES_PATH"),
            max_shipping_days=_int("IMGA_MAX_SHIPPING_DAYS", DEFAULT_MAX_SHIPPING_DAYS),
            max_warehouse_days=_int("IMGA_MAX_WAREHOUSE_DAYS", DEFAULT_MAX_WAREHOUSE_DAYS),
            jwt=jwt,
            cookies=cookies,
            batch=batch,
            report=report,
            enable_public_demo_endpoints=enable_public_demo_endpoints,
            imga_api_trial_key=trial_key_raw,
            token_pepper=token_pepper_raw,
            environment=env_name,
        )
