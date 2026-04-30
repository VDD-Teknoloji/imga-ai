.PHONY: help seed-dev seed-dev-reset

PYTHON ?= python

help:
	@echo "Available targets:"
	@echo "  make seed-dev          Idempotent dev seed (Acme tenant + 3 users + 18 tickets)"
	@echo "  make seed-dev-reset    Drop Acme tenant + all its tickets, then seed fresh"

seed-dev:
	$(PYTHON) scripts/seed_dev_tenant.py

seed-dev-reset:
	$(PYTHON) scripts/seed_dev_tenant.py --reset
