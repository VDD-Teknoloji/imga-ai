# imga-dashboard

Streamlit dashboard built on top of `imga-core`. Replaces the legacy
`legacy/app.py` prototype with a clean, modular UI.

Layers:

- `app.py` — Streamlit entry point (file upload, tabs, state management)
- `services.py` — pipeline construction with caching
- `views/` — one module per tab (executive summary, detail, rules, SLA params)

## Run locally

```bash
pip install -e ".[dev]"
streamlit run src/imga_dashboard/app.py
```

## Run in Docker

```bash
docker compose up -d dashboard
```

UI on `http://localhost:8502` (port configurable via `IMGA_DASHBOARD_PORT`).
