# imga-ai — agent guide

Turkish customer-review sentiment analysis SaaS, multi-tenant. This file
captures project-wide context that isn't obvious from the code: the
load-bearing invariants, the gotchas that have already bitten us, and
where to look for things.

## Repo layout

```
packages/
  imga-core/         BERT pipeline + override layers (no internal deps)
  imga-db/           SQLAlchemy models + Alembic migrations + RLS helpers
  imga-api/          FastAPI: auth, tenants, tickets, analyze, admin
  imga-web/          Next.js 16 + React 19 frontend  (see its own AGENTS.md)
  imga-dashboard/    Streamlit ops UI
docs/                roadmap, user guide (Turkish), workflow notes
infra/               server-setup runbook + per-project compose stacks
legacy/              original Streamlit prototype (reference only)
```

Dependency order for builds: `imga-core` → `imga-db` → `imga-api`. The
API Dockerfile bakes both into the image; missing the path-dep step is
the #1 reason a fresh build fails.

## Auth + multi-tenancy (load-bearing — read before touching)

- **Three Postgres roles** (created by `imga-db/sql/` init scripts):
  - `imga_owner` — DDL + role management. Used by Alembic only.
  - `imga_app` — RLS-bound app role. Used by every per-request session.
  - `imga_admin` — RLS-bypass via FORCE-aware path. Used for cross-tenant
    operations (super-admin, login, /me, /switch-tenant). Pick the
    correct role-bound dependency in route definitions.
- **RLS+FORCE on every tenant-scoped table.** Policies read
  `current_setting('app.current_tenant_id')::uuid`. The middleware sets
  it as the first statement on each request. If you add a tenant-scoped
  table, mirror the convention in [migration 0006](packages/imga-db/src/imga_db/alembic/versions/20260106_0000_0006_tickets_and_transitions.py).
- **JWT claims:** `sub`, `email`, `is_super_admin`, `active_tenant_id`,
  `active_role`, `type` (`access` or `refresh`), plus `iat`/`exp`. The
  access-token TTL is 15 min; refresh TTL is 7 days, single-use,
  rotation-chain compromise detected by `parent_jti` graph.
- **Refresh preserves tenant context** (since migration 0011). Earlier
  silent rotations dropped `active_tenant_id` and broke every
  tenant-scoped endpoint 15 min after login. If you change refresh,
  keep the [tenant carry-over](packages/imga-api/src/imga_api/services/auth_service.py#L161).
- **User roles:** super-admins are global (cross-tenant); per-tenant
  membership lives in `user_tenants` with `tenant_admin` / `analyst` /
  `viewer`. `/auth/switch-tenant` opens a brand-new refresh family —
  don't try to mutate the active one.

## Local development

```bash
# Full stack — postgres + api + dashboard + web
docker compose up -d

# Test database (separate port — DO NOT mix with dev :5432)
IMGA_POSTGRES_PORT=5433 docker compose up -d postgres

# Per-package
(cd packages/imga-core && pytest)
(cd packages/imga-api && pytest)
(cd packages/imga-db && pytest)
(cd packages/imga-web && pnpm test && pnpm exec playwright test)
```

Tests in `imga-api` and `imga-db` require **live Postgres on :5433** —
RLS is a Postgres-only feature, no SQLite fallback.

Pre-commit (`ruff` + `mypy` strict + standard hygiene) must pass before
push; CI will reject otherwise. Don't bypass with `--no-verify`.

## Production deploy

- **Hosts:** `app.imga.ai` + `api.imga.ai` (production), `staging.imga.ai`
  + `api-staging.imga.ai` (staging). DNS via Cloudflare, A-records only.
- **Compose stacks** at `infra/imga/{production,staging}/` join three
  networks: project-internal (`imga-{prod,staging}-internal`),
  shared `caddy-public`, and (for the api) the project DB network.
- **Caddy is shared**, lives at `/opt/shared/caddy/` on the VPS. Per-
  project configs go in `/opt/shared/caddy/conf.d/imga-*.conf`. Don't
  add a new Caddy container.
- **Routine redeploy** (after first-time setup is done):

  ```bash
  git pull origin main
  ENV=production            # or staging
  COMPOSE=/opt/imga/infra/imga/$ENV/docker-compose.yml
  sudo docker compose -f $COMPOSE build <svc>          # api or web — independent images
  sudo docker compose -f $COMPOSE up -d <svc>
  sudo docker compose -f $COMPOSE exec api alembic upgrade head   # only if new migration
  ```

  Migrations are **not** auto-run on container start (api launches
  straight into `uvicorn`); `alembic upgrade head` against
  `DATABASE_URL_OWNER` is a manual step. Web and api images are
  independent — touch only what changed.
- **DB inspection from the host:**
  `sudo docker compose -f $COMPOSE exec postgres psql -U imga_owner -d imga`.
  `imga_owner` bypasses RLS; use `imga_app` if you want to verify a
  policy actually filters.
- **Healthcheck quirk:** Alpine + BusyBox wget doesn't fall back from
  IPv6 to IPv4. All healthchecks bind `127.0.0.1`, never `localhost` —
  see comments in [production compose](infra/imga/production/docker-compose.yml).
- **First-time runbook:** [`infra/imga/deploy.md`](infra/imga/deploy.md)
  for the 10-section on-server ritual (DNS, env files, Caddy bootstrap,
  super-admin creation).
- **Agent setup on a fresh deploy server:**
  `bash scripts/setup-claude-agent.sh` installs per-host Claude Code
  permissions (gitignored `.claude/settings.local.json` — allow/deny/ask
  rules + `autoMode` classifier guidance for routine compose ops) and
  the bash audit log at `/var/log/claude-agent/bash.log`.
- **End-user docs:** [`docs/user-guide.md`](docs/user-guide.md) (Turkish).

## Conventions

- **Commits:** Conventional Commits with package scope. Full guide at
  [`docs/git-workflow.md`](docs/git-workflow.md). One logical change per PR.
- **Comments:** Default to none. Add only when the *why* is non-obvious
  — a hidden constraint, a workaround, behavior that would surprise a
  reader. Don't restate the code. Existing comments mix Turkish + English
  in infra/business-logic context; that's intentional, follow the local
  style of the file you're editing.
- **No emoji** in code, commits, or files unless explicitly requested.
- **Mypy strict** for Python; **TypeScript strict** for the web. No
  `any`, no `# type: ignore` without a one-line justification.
- **Don't add scope creep.** A bug fix doesn't need refactoring around
  it; a one-shot operation doesn't need a helper.

## Where to look

- **Current sprint state / roadmap** — [`docs/post-sprint-7-roadmap.md`](docs/post-sprint-7-roadmap.md).
- **Architecture decisions** — [`infra/multi-project-architecture.md`](infra/multi-project-architecture.md)
  has the 5 locked-in calls (shared Caddy, network topology, etc.).
- **Frontend specifics** — [`packages/imga-web/AGENTS.md`](packages/imga-web/AGENTS.md).
  Next.js 16 + React 19 has breaking changes from training data; read
  `node_modules/next/dist/docs/` before guessing.
- **Existing migrations** are the canonical reference for adding new
  tables (RLS policy syntax, index naming, FK cascade choices).
