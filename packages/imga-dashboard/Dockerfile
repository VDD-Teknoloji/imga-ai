# syntax=docker/dockerfile:1.7
# imga-dashboard: Streamlit UI built on imga-core. Build context = repo root.

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

RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.0,<3.0"

COPY packages/imga-core/pyproject.toml packages/imga-core/README.md /build/imga-core/
COPY packages/imga-core/src /build/imga-core/src
RUN pip install --no-cache-dir /build/imga-core

COPY packages/imga-dashboard/pyproject.toml packages/imga-dashboard/README.md /build/imga-dashboard/
COPY packages/imga-dashboard/src /build/imga-dashboard/src
RUN pip install --no-cache-dir /build/imga-dashboard

# Pre-download BERT model (see imga-api/Dockerfile for rationale).
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
    HF_HOME=/cache/huggingface \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 imga \
 && mkdir -p /cache/huggingface /data /app \
 && chown -R imga:imga /cache /data /app

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder --chown=imga:imga /cache/huggingface /cache/huggingface

USER imga

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["python", "-m", "streamlit", "run", "/usr/local/lib/python3.11/site-packages/imga_dashboard/app.py"]
