.PHONY: help seed-dev seed-dev-reset api-dev web-dev

PYTHON ?= python

help:
	@echo "Available targets:"
	@echo "  make api-dev           Start uvicorn on :8003 (reads packages/imga-api/.env)"
	@echo "  make web-dev           Start Next.js dev server on :3000"
	@echo "  make seed-dev          Idempotent dev seed (Acme tenant + 3 users + 18 tickets)"
	@echo "  make seed-dev-reset    Drop Acme tenant + all its tickets, then seed fresh"

seed-dev:
	$(PYTHON) scripts/seed_dev_tenant.py

seed-dev-reset:
	$(PYTHON) scripts/seed_dev_tenant.py --reset

# Reads packages/imga-api/.env (copy from .env.example on first use).
api-dev:
	cd packages/imga-api && uvicorn imga_api.main:app --port 8003 --host 0.0.0.0 --reload

web-dev:
	cd packages/imga-web && npm run dev
