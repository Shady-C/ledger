SHELL := /bin/sh

COMPOSE ?= docker compose
PNPM ?= pnpm
UV ?= uv
WORKER_DIR := services/worker

.DEFAULT_GOAL := help

.PHONY: help up down logs ps build migrate seed test test-ts test-python check check-ts check-python smoke phase2-db-acceptance benchmark-analytics im-bank-tz-acceptance

help:
	@echo "Ledger development commands"
	@echo "  make up            Build and start the local stack"
	@echo "  make down          Stop the local stack (data volumes are preserved)"
	@echo "  make migrate       Apply pending database migrations with dbmate in Docker"
	@echo "  make seed          Apply migrations and load idempotent development seed data"
	@echo "  make test          Run TypeScript and Python test suites"
	@echo "  make check         Run TypeScript checks plus Python lint and type checks"
	@echo "  make smoke         Exercise the golden API ingestion path (stack must be healthy)"
	@echo "  make phase2-db-acceptance  Verify Phase 2 migrations in disposable databases"
	@echo "  make benchmark-analytics  Run the disposable 100k Phase 2 analytics benchmark"
	@echo "  make im-bank-tz-acceptance  Validate supplied sanitized I&M Tanzania PDFs"

up:
	$(COMPOSE) up --build --remove-orphans

down:
	$(COMPOSE) down --remove-orphans

logs:
	$(COMPOSE) logs --follow --tail=200

ps:
	$(COMPOSE) ps

build:
	$(PNPM) build
	$(COMPOSE) build web worker

migrate:
	$(COMPOSE) run --rm migrate

seed: migrate
	$(COMPOSE) run --rm seed

test: test-ts test-python

test-ts:
	$(PNPM) test

test-python:
	cd $(WORKER_DIR) && $(UV) sync --frozen --extra dev
	cd $(WORKER_DIR) && $(UV) run --frozen --extra dev python -m pytest -p no:cacheprovider

check: check-ts check-python

check-ts:
	$(PNPM) check

check-python:
	cd $(WORKER_DIR) && $(UV) sync --frozen --extra dev
	cd $(WORKER_DIR) && $(UV) run --frozen --extra dev python -m ruff check --no-cache worker tests ../../scripts/phase0_smoke.py ../../scripts/phase1_smoke.py ../../scripts/phase2_smoke.py ../../scripts/phase2_db_acceptance.py ../../scripts/phase2_analytics_benchmark.py ../../scripts/im_bank_tz_pdf_acceptance.py
	cd $(WORKER_DIR) && $(UV) run --frozen --extra dev python -m mypy worker ../../scripts/phase0_smoke.py ../../scripts/phase1_smoke.py ../../scripts/phase2_smoke.py ../../scripts/phase2_db_acceptance.py ../../scripts/phase2_analytics_benchmark.py ../../scripts/im_bank_tz_pdf_acceptance.py

smoke:
	$(UV) run --project $(WORKER_DIR) --frozen --extra dev python scripts/phase2_smoke.py

phase2-db-acceptance:
	$(UV) run --project $(WORKER_DIR) --frozen --extra dev python scripts/phase2_db_acceptance.py

benchmark-analytics:
	$(UV) run --project $(WORKER_DIR) --frozen --extra dev python scripts/phase2_analytics_benchmark.py

im-bank-tz-acceptance:
	$(UV) run --project $(WORKER_DIR) --frozen --extra dev python scripts/im_bank_tz_pdf_acceptance.py
