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

# Install imga-core first (path dep), then imga-api.
COPY packages/imga-core/pyproject.toml packages/imga-core/README.md /build/imga-core/
COPY packages/imga-core/src /build/imga-core/src
RUN pip install --no-cache-dir /build/imga-core

COPY packages/imga-api/pyproject.toml packages/imga-api/README.md /build/imga-api/
COPY packages/imga-api/src /build/imga-api/src
RUN pip install --no-cache-dir /build/imga-api

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

USER imga

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "imga_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
