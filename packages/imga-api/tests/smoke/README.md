# Post-deploy smoke tests

Sprint 9.4 J — gated regression suite for the three Sprint 9.4 P1
fixes (period mapping, KPI window, dimension propagation). The
default test compose skips this directory; an operator runs the
suite explicitly after a production / staging deploy:

```bash
sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml \
  exec -T api env RUN_SMOKE=1 pytest tests/smoke/ -v
```

Why gated: each test exercises an end-to-end path that's slow and
side-effecting (DB inserts, real briefing generation). They're
complementary to the unit suites — those pin contracts, the smoke
tests pin "the wire-up is intact in this environment".

Pre-9.4 the smoke story was "open the page, see the toast, declare
victory". That missed three demo-blocker bugs because none of them
reach into the UI: the period mapping flipped a backend column,
the KPI window changed a number, the dimensions skipped a column.
The pattern here — "assert the row landed in the DB with the right
value" — is the failure mode the smoke story was missing.
