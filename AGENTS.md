# Repository Guidelines

## Project Scope and Structure

Ledger is a Phase 3 personal-finance application with an executable local
stack. Read `docs/PROJECT_CONTEXT.md` first for the active phase and scope,
treat `docs/ARCHITECTURE.md` as the system-design reference, preserve
`docs/BUILD-PLAN.md`, `docs/PHASE-1-BUILD-PLAN.md`, and
`docs/PHASE-2-BUILD-PLAN.md` as completed historical records, and use
`docs/PHASE-3-BUILD-PLAN.md` for the active acceptance gates. Keep work within
the current phase unless scope is explicitly updated.

The monorepo layout is:

- `apps/web/`: SvelteKit UI, PWA, and server routes.
- `packages/shared-types/`: canonical TypeScript models and query schemas.
- `services/worker/worker/`: Python/Polars ingestion and analytics.
- `services/worker/tests/`: worker tests, with sanitized fixtures in `fixtures/`.
- `db/migrations/`: ordered SQL migrations.
- `docs/`: source-of-truth architecture, requirements, plans, and decisions.

## Build, Test, and Development Commands

The supported project interface is:

- `docker compose up`: start the web app, worker, Postgres, and MinIO.
- `make up` / `make down`: start or stop the local stack.
- `make migrate`: apply database migrations.
- `make seed`: load development data.
- `make test`: run all project tests.
- `make check`: run TypeScript checks plus Python `ruff` and strict `mypy`.
- `make smoke`: exercise the Phase 3 stub-provider flow, including the golden
  ingestion path, against a healthy fresh stack.
- `make ask-live-acceptance`: run the opt-in manual Anthropic acceptance gate;
  never run it in ordinary CI.

CI must also run TypeScript typechecking plus Python `ruff` and `mypy`. Do not document a command as available until its supporting file is committed.

## Coding Style and Naming

Use two-space indentation for TypeScript, Svelte, JSON, and YAML; use four spaces for Python. Follow SvelteKit route names (`+page.svelte`, `+server.ts`), `snake_case` for Python modules and functions, and `PascalCase` for components, classes, and exported types. Keep financial calculations deterministic, use explicit currency fields, and never delegate arithmetic to an LLM. Apply formatter and linter configurations once they are added; avoid unrelated formatting churn.

## Testing Guidelines

Python tests use pytest and follow `test_*.py` naming. Financial changes require
regression coverage. Preserve the golden reconciliation assertion (closing
balance `2855.59`), verify repeat ingestion adds zero rows, and test adapter
detection, sign handling, foreign-spend parsing, coverage-gap handling, market
isolation, and CAD/TZS generation fencing. Phase 3 Ask changes also require
strict contract, SQL-parameterization, provider-privacy,
deterministic-fallback, accessibility, and adversarial coverage. No numeric
coverage threshold exists; critical ledger, reconciliation, analytics, and
grounded-answer paths must be covered.

## Commits and Pull Requests

Use `type(scope): description [JIRA-KEY]`, with `feat`, `fix`, `docs`,
`refactor`, `test`, or `chore`. Pull requests should describe Phase 3 scope,
link the Jira issue when configured, include test/lint results, and add
screenshots for UI changes. Any deviation from documented architecture
requires an ADR in `docs/decisions/`, related documentation updates, and a
`CHANGELOG.md` entry.

## Security and Configuration

Commit `.env.example`, never `.env` or credentials. Keep account identifiers
masked, sanitize statement fixtures, and minimize financial data sent to
external AI services. The Ask planner must never receive schema, SQL, rows,
results, or entity catalogs; the narrator may receive only request-local opaque
fact references. Never log or persist Ask questions, plans, evidence, results,
or prose.
