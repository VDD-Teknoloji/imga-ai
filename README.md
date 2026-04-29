# imga-ai

Turkish customer-review sentiment analysis platform.

## Quick start

```bash
docker compose up -d
```

| Service | URL |
|---|---|
| API (Swagger) | http://localhost:8003/docs |
| Dashboard | http://localhost:8502 |
| Legacy UI (opt-in: `--profile legacy`) | http://localhost:8501 |

## Repo layout

```
packages/imga-core/        sentiment pipeline (BERT + override layers)
packages/imga-api/         FastAPI HTTP wrapper around imga-core
packages/imga-dashboard/   Streamlit UI built on imga-core
legacy/                    original Streamlit prototype (reference only)
```

## Developer setup

```bash
# Install all packages in editable mode + dev deps
for pkg in imga-core imga-api imga-dashboard; do
  pip install -e "packages/$pkg[dev]"
done

# Pre-commit hooks (ruff + mypy + standard checks)
pip install pre-commit
pre-commit install

# Run tests per package
(cd packages/imga-core && pytest)        # 76 passed
(cd packages/imga-api && pytest)         # 10 passed
(cd packages/imga-dashboard && pytest)   #  7 passed

# Lint + type
for pkg in imga-core imga-api imga-dashboard; do
  ruff check "packages/$pkg/src" "packages/$pkg/tests"
  (cd "packages/$pkg" && python -m mypy src)
done
```

## Docker workflows

```bash
docker compose up -d                                        # api + dashboard
docker compose --profile test run --rm core-tests           # core unit tests
docker compose --profile slow run --rm core-tests-slow      # BERT snapshot tests
docker compose --profile legacy up -d                       # legacy Streamlit UI
```

See `.env.example` for host port + data path overrides.

## Documentation

- `docs/legacy-analysis.md` — original prototype code review
- `docs/git-workflow.md` — branching + commit conventions
