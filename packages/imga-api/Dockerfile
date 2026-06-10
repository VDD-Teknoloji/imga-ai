# syntax=docker/dockerfile:1.7
# imga-api: FastAPI service. Build context = repo root (needs both packages).

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

# CPU-only torch wheels first.
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.0,<3.0"

# Install path deps in dependency order: imga-core (no internal
# deps) → imga-db (no internal deps) → imga-api (depends on both).
# If imga-db install is skipped, `pip install /build/imga-api` tries
# to resolve the "imga-db" requirement from PyPI and fails with
# "No matching distribution found" — there is no PyPI-published
# package by that name; it lives in this monorepo.
COPY packages/imga-core/pyproject.toml packages/imga-core/README.md /build/imga-core/
COPY packages/imga-core/src /build/imga-core/src
RUN pip install --no-cache-dir /build/imga-core

COPY packages/imga-db/pyproject.toml packages/imga-db/README.md /build/imga-db/
COPY packages/imga-db/src /build/imga-db/src
RUN pip install --no-cache-dir /build/imga-db

COPY packages/imga-api/pyproject.toml packages/imga-api/README.md /build/imga-api/
COPY packages/imga-api/src /build/imga-api/src
RUN pip install --no-cache-dir /build/imga-api

# Sprint 11.0 — BERT model bake KALDIRILDI (~440 MB image tasarrufu).
# Sentiment artık birincil olarak Gemini unified'dan; BERT zincirin
# son halkası: önce uzak Modal servisi (IMGA_REMOTE_BERT_URL), o da
# yoksa lokal lazy yükleme — model HF Hub'dan İLK kullanımda iner ve
# HF_HOME volume'ünde/container yaşamında cache'lenir. Normal
# işleyişte bu yol hiç ısınmaz.
ENV HF_HOME=/cache/huggingface

# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/cache/huggingface

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    curl \
    # Sprint 8.3.6.5 — WeasyPrint runtime deps. Pango + Cairo +
    # GdkPixbuf for the renderer; Harfbuzz for OpenType shaping;
    # the dejavu/liberation font packs so PDFs have working Türkçe
    # glyphs (ı/ş/ğ etc.) without bundling fonts in the repo. Adds
    # ~80-100 MB to the image; accepted trade-off for executive
    # PDF deliverables.
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    fonts-dejavu-core \
    fonts-liberation \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 imga \
 && mkdir -p /cache/huggingface /data /app \
 && chown -R imga:imga /cache /data /app

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
# Sprint 11.0 — model bake yok; /cache/huggingface boş ve imga-owned
# kalır (yukarıdaki mkdir). Acil-durum lokal BERT'i ilk kullanımda
# buraya indirir.

# Runtime alembic.ini — points script_location at the installed
# imga_db package's alembic dir (absolute path, since WORKDIR /app
# can't reach the dev-only relative path). `alembic upgrade head`
# from /app picks this up automatically (alembic looks for
# alembic.ini in CWD by default).
COPY --chown=imga:imga packages/imga-api/alembic.ini /app/alembic.ini

USER imga

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "imga_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# Sprint 9.4 J — smoke-runtime stage.
#
# Derives from the production ``runtime`` stage and layers in pytest +
# the tests/ tree so the post-deploy smoke suite (``tests/smoke/``) can
# run against a deployed environment without a separate pip install
# dance on the host. The base ``runtime`` image stays minimal — pytest
# isn't shipped to prod, only to the smoke profile.
#
# Build only when needed:
#   docker compose --profile smoke build api-smoke
#
# Run once and exit:
#   sudo docker compose --profile smoke run --rm api-smoke
#
# The smoke tests write to the database (seeded fixtures, then cleaned
# up via ``semi_auto_tenant``'s teardown). Run against staging by
# default; run against production only with a healthy backup and the
# expectation that the test tenant is created and removed within the
# suite.
FROM runtime AS smoke-runtime

# pytest needs root to write its cache to the imga-owned /app; switch
# back to root for the install + test copy, then leave the image
# running as root (smoke containers are short-lived, no exposure).
USER root

# Sprint 9.4 J — keep the dep list in sync with the test compose's
# inline install (infra/imga/test/docker-compose.yml). pytest-asyncio
# is the only must-have beyond pytest itself for the smoke tests;
# pytest-timeout + factory-boy + httpx + fakeredis are inherited from
# the dev environment but the smoke suite doesn't need them.
RUN pip install --no-cache-dir pytest pytest-asyncio

# tests/ + conftest.py — conftest is at the same level as tests/
# (packages/imga-api/tests/conftest.py) so pytest discovers it
# automatically. /app/tests mirrors the working directory layout
# pytest discovery expects.
COPY packages/imga-api/tests /app/tests
# pyproject.toml carries the pytest config block (asyncio_mode, etc.)
# the suite expects; copying it keeps the smoke run aligned with the
# in-repo pytest config without a stand-alone pytest.ini.
COPY packages/imga-api/pyproject.toml /app/pyproject.toml

# Gate the suite — pytest.mark.skipif on every smoke test consults
# this env var so a forgotten override doesn't fire the suite from
# an interactive session.
ENV RUN_SMOKE=1

# Smoke runs need to talk to the DB; the test fixtures rely on the
# same env vars the api service consumes (DATABASE_URL_OWNER + co.).
# Override the inherited uvicorn CMD with the smoke pytest invocation.
# --tb=short keeps the failure output legible across compose's line-
# buffered logs.
CMD ["python", "-m", "pytest", "/app/tests/smoke/", "-v", "--tb=short"]

# The healthcheck inherited from the runtime stage probes /health on
# port 8000 — smoke containers don't serve HTTP, so disable it to
# avoid the cosmetic "unhealthy" flag on a short-lived run.
HEALTHCHECK NONE
