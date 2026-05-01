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

# Pre-download BERT model into HF cache so the runtime image starts cold
# without an HF Hub call. Cached as a Docker layer keyed on the model id;
# subsequent rebuilds reuse it as long as the model id stays the same.
ENV HF_HOME=/cache/huggingface
RUN mkdir -p /cache/huggingface \
 && python -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification; \
m='savasy/bert-base-turkish-sentiment-cased'; \
AutoTokenizer.from_pretrained(m); \
AutoModelForSequenceClassification.from_pretrained(m)"

# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/cache/huggingface

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 imga \
 && mkdir -p /cache/huggingface /data /app \
 && chown -R imga:imga /cache /data /app

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
# Bake the BERT model into the image (~440MB) so first /analyze is a
# disk-to-memory load, not an HF download.
COPY --from=builder --chown=imga:imga /cache/huggingface /cache/huggingface

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
