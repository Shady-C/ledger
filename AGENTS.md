# Repository Guidelines

## Project Scope and Structure

Ledger is a Phase 0 personal-finance application with an executable local
stack. Read `docs/PROJECT_CONTEXT.md` first for the active phase and scope,
treat `docs/ARCHITECTURE.md` as the system-design reference, and use
`docs/BUILD-PLAN.md` for the Phase 0 acceptance gates. Keep work within the
current phase unless scope is explicitly updated.

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
- `make smoke`: exercise the golden API ingestion path against a healthy fresh stack.

CI must also run TypeScript typechecking plus Python `ruff` and `mypy`. Do not document a command as available until its supporting file is committed.

## Coding Style and Naming

Use two-space indentation for TypeScript, Svelte, JSON, and YAML; use four spaces for Python. Follow SvelteKit route names (`+page.svelte`, `+server.ts`), `snake_case` for Python modules and functions, and `PascalCase` for components, classes, and exported types. Keep financial calculations deterministic, use explicit currency fields, and never delegate arithmetic to an LLM. Apply formatter and linter configurations once they are added; avoid unrelated formatting churn.

## Testing Guidelines

Python tests use pytest and follow `test_*.py` naming. Financial changes require
regression coverage. Preserve the golden reconciliation assertion (closing
balance `2855.59`), verify repeat ingestion adds zero rows, and test adapter
detection, sign handling, foreign-spend parsing, and coverage-gap handling. No
numeric coverage threshold exists; critical ledger and reconciliation paths
must be covered.

## Commits and Pull Requests

There is no Git history yet. Use `type(scope): description [JIRA-KEY]`, with `feat`, `fix`, `docs`, `refactor`, `test`, or `chore`. Pull requests should describe Phase 0 scope, link the Jira issue, include test/lint results, and add screenshots for UI changes. Any deviation from documented architecture requires an ADR in `docs/decisions/`, related documentation updates, and a `CHANGELOG.md` entry.

## Security and Configuration

Commit `.env.example`, never `.env` or credentials. Keep account identifiers masked, sanitize statement fixtures, and minimize financial data sent to external AI services.
