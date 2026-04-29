# Git workflow

## Branching

- `main` — protected. No direct pushes; merge only via PR.
- Feature work: short-lived branches off `main`, prefix by intent:
  - `feat/<topic>` — new functionality
  - `fix/<topic>` — bug fixes
  - `chore/<topic>` — infra, deps, tooling
  - `refactor/<topic>` — internal restructure, no behavior change
  - `test/<topic>` — adding/expanding tests
  - `docs/<topic>` — documentation only
- Delete branches after merge.

## Commit messages

Conventional Commits: `<type>(<scope>): <subject>`.

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`.

Scope is the package or area: `core`, `api`, `dashboard`, `parity`, `docker`, `ci`.

Examples:

```
feat(core): add tier-2 fallback override
fix(api): handle empty body in /analyze/batch
test(parity): pin legacy BERT outputs as snapshot fixtures
chore(docker): rebuild core-tests with smart rules included
```

Subject ≤ 72 chars, lowercase, imperative mood, no trailing period.

## Pull requests

- One logical change per PR.
- CI (`.github/workflows/ci.yml`) must be green: lint, mypy strict, pytest, docker build.
- Pre-commit must pass locally before push.
- Squash-merge by default; only use merge commits for cross-package work.

## Versioning

Each package owns its own version in `pyproject.toml`. Bump with the change that
introduces it; do not batch version bumps.
