# E2E tests (Playwright)

Seven specs across three files, covering the five critical flows
called out in the Sprint 7.6.6 plan plus a structural a11y gate:

| File | Test | Flow |
|------|------|------|
| auth.spec.ts | happy path | login form → dashboard renders four metric cards |
| auth.spec.ts | invalid creds | wrong password → toast + still on /login |
| ticket-flow.spec.ts | filter | URL-bound `?state=open` filter shows 5 / 18 |
| ticket-flow.spec.ts | claim | OPEN ticket → "Üstlen" → state becomes İşlemde |
| ticket-flow.spec.ts | role guard | charlie (viewer) on /settings → "Yetkiniz yok" |
| a11y.spec.ts | landmarks | login page focusable form, single h1 |
| a11y.spec.ts | dashboard a11y | main / nav / aside landmarks + named icon buttons |

## Pre-reqs

The tests assume the same dev stack the rest of Sprint 7.6 uses:

```sh
docker compose up -d postgres                           # postgres on :5433
make seed-dev-reset                                     # tertemiz Acme seed (idempotent)
make api-dev                                            # uvicorn :8003 (.env auto-loaded)
```

The Playwright `webServer` block boots the Next.js dev server itself
when the suite runs, so the developer doesn't need to pre-launch
`npm run dev`.

The "claim" test mutates state (one OPEN ticket → IN_PROGRESS). Run
`make seed-dev-reset` between local iterations or the second run
will see four OPEN tickets, the third three, etc. CI environments
should run the reset target as part of the e2e job.

## Running

```sh
# from packages/imga-web
npm run test:e2e          # headless; full suite
npm run test:e2e:ui       # Playwright UI mode (interactive)
npx playwright test auth  # match by file/test name
```

Reports land in `playwright-report/` (HTML) and `test-results/`
(traces, videos on failure). Both are gitignored.

## Why no axe-core / Lighthouse

80/20 — adding @axe-core/playwright would cover more WCAG rules but
the structural checks here (single h1, landmarks present, icon
buttons named) catch the regressions our customers actually hit.
Drop the auditor in if a real-world a11y bug surfaces.
