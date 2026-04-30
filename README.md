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

## API Reference

Local development (with `docker compose up -d`):

| Endpoint | URL |
|---|---|
| Swagger UI (interactive) | http://localhost:8003/docs |
| ReDoc (read-only) | http://localhost:8003/redoc |
| OpenAPI JSON | http://localhost:8003/openapi.json |

Authentication: send `Authorization: Bearer <access_token>` on every
non-public endpoint. Tokens come from `POST /auth/login` and are
rotated by `POST /auth/refresh`. The refresh token is single-use —
replaying a consumed token revokes the entire session family.

Initial bootstrap: the super-admin user is seeded by migration `0001`
from the `SUPER_ADMIN_EMAIL` and `SUPER_ADMIN_INITIAL_PASSWORD`
environment variables. After first login, change the password via
`POST /auth/change-password` (this also invalidates every live access
token issued before the change).

For frontend dev work, populate a realistic tenant (Acme Inc + 3 users
+ 18 sample tickets) with `make seed-dev`. The script is idempotent;
`make seed-dev-reset` drops + reseeds. Login as `alice@acme.com /
dev123` to see all four dashboard cards lit up.

Tag groups in Swagger UI:

- **Auth** — login, refresh rotation, switch-tenant, password change
- **Admin: Tenants** / **Admin: Users** — Sprint 7.5.5 (placeholders)
- **Tenant Config** — automation mode, category taxonomy
- **Analyze** — sentiment + categorization pipeline
- **Tickets** — ticket CRUD + state machine transitions
- **Health** — `/health` probe

## Documentation

- `docs/legacy-analysis.md` — original prototype code review
- `docs/git-workflow.md` — branching + commit conventions
- `docs/post-sprint-7-roadmap.md` — 4-grup borç roadmap'i (7.5.5, API consistency, Sprint 8, sonrası)
