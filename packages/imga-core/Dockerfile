# syntax=docker/dockerfile:1.7
# imga-core: containerized package for tests and as a base layer for downstream services.

ARG PYTHON_VERSION=3.11

# ---------------------------------------------------------------------------
# Builder: install deps + the package
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

# CPU-only torch wheels first (significantly smaller than the default CUDA build).
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.0,<3.0"

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[dev]"

# ---------------------------------------------------------------------------
# Runtime: minimal layer for running the package
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/cache/huggingface

RUN useradd --create-home --uid 1000 imga \
 && mkdir -p /cache/huggingface /data /app \
 && chown -R imga:imga /cache /data /app

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --chown=imga:imga pyproject.toml README.md ./
COPY --chown=imga:imga src ./src
COPY --chown=imga:imga tests ./tests

USER imga

# Default: run the test suite. Override the CMD for production (e.g. an API).
CMD ["python", "-m", "pytest", "tests/", "-v"]
