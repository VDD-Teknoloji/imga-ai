# imga-db

SQLAlchemy 2.0 + Alembic data layer for the imga platform.

## Layout

```
src/imga_db/
├── base.py             SQLAlchemy DeclarativeBase
├── session.py          async sessionmaker + DSN helpers
├── rls.py              RLS context helpers (set_current_tenant)
├── models/
│   ├── mixins.py       TimestampMixin, SoftDeleteMixin, TenantOwnedMixin
│   ├── tenant.py       Tenant, TenantPlanTier, AutomationMode
│   ├── user.py         User, UserTenantLink, UserTenantRole
│   └── audit.py        AuditLog
└── alembic/            migrations directory
```

## Multi-tenancy strategy

Single Postgres database, single schema, `tenant_id` column on every
tenant-scoped table, plus RLS (Row-Level Security) policies enforcing
`tenant_id = current_setting('app.current_tenant_id')::uuid`.

The API middleware sets `app.current_tenant_id` on every request as
the first DB statement, so any subsequent query is automatically scoped
to the active tenant.

## Test database

Tests require a real PostgreSQL instance (RLS is a Postgres-only feature).
The compose stack provides one as the `postgres` service:

```bash
docker compose up -d postgres
TEST_DATABASE_URL=postgresql+asyncpg://imga:imga_dev_password@localhost:5432/imga_test pytest
```
