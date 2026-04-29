# imga-api

FastAPI HTTP wrapper around `imga-core`.

## Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | — | `{"status": "ok", "version": "..."}` |
| POST | `/analyze` | `{"text": "..."}` | `AnalysisResult` |
| POST | `/analyze/batch` | `{"texts": ["...", "..."]}` | `[AnalysisResult]` |
| POST | `/metrics` | `{"results": [AnalysisResult, ...]}` | `ExecutiveMetrics` |

## Run locally

```bash
pip install -e ".[dev]"
uvicorn imga_api.main:app --reload --port 8000
```

## Configuration (env vars)

| Variable | Default | Description |
|---|---|---|
| `IMGA_BERT_MODEL` | `savasy/bert-base-turkish-sentiment-cased` | HF model name |
| `IMGA_KB_PATH` | _unset_ | Path to `training_data.csv` knowledge base |
| `IMGA_RULES_PATH` | _unset_ | Path to `cx_rules.json` smart rules |
| `IMGA_MAX_SHIPPING_DAYS` | `3` | SLA limit |
| `IMGA_MAX_WAREHOUSE_DAYS` | `2` | SLA limit |

## Test

```bash
pytest tests/
```
