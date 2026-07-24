# Ledger

Ledger is a self-hostable personal-finance ledger that imports statement files,
normalizes them into one canonical model, reconciles every statement with exact
decimal arithmetic, and presents balances, cash flow, and searchable
transactions in an installable web app.

Phase 1 keeps every financial operation deterministic while using optional,
structured AI proposals for unknown tabular layouts and previously unseen
merchants. A model never computes or writes balances, FX values, reconciliation,
or net worth.

## Quick start

Requirements: Docker with Compose and Make.

```sh
cp .env.example .env
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). The fresh local stack
creates a sanitized Amex development account automatically, so you can upload
an Amex XLSX, conventional CSV, OFX/QFX statement, or a deterministically
extractable PDF immediately. MinIO's local console is available at
[http://localhost:9001](http://localhost:9001).

The values in `.env.example` are development defaults only. Replace every
password before exposing the stack beyond your own machine, and never commit a
real `.env` file or statement data. Replace and securely back up
`STATEMENT_ENCRYPTION_KEY` as well: losing that key makes stored raw statements
unreadable. `ANTHROPIC_API_KEY` is optional; without it, deterministic imports
remain available, unknown CSV/XLSX imports report `needs_ai`, and existing
categorization proposals remain reviewable. New categorization jobs require a
configured provider (or `WORKER_PROVIDER_MODE=stub` for deterministic tests).

## Common commands

```sh
make up          # build and run the complete stack
make down        # stop it without deleting data volumes
make migrate     # apply ordered SQL migrations
make seed        # load idempotent reference data and the development account
make test        # run TypeScript and Python tests
make check       # typecheck TypeScript; lint and typecheck Python
make smoke       # run the golden API flow against a healthy fresh stack
```

Local quality commands require Node.js 22+, pnpm 11, and uv. uv installs the
locked Python 3.12 worker environment from `services/worker/uv.lock`, so the
host's system Python is not used.

The Phase 1 smoke test is designed to generate sanitized statements in memory,
preserve the Phase 0 closing balance of `2855.59`, verify idempotent repeat
ingestion, and exercise Phase 1 account, valuation, and route contracts. It does
not read private test fixtures. Final integrated smoke acceptance is recorded,
and Phase 1 is now `in_review`.

For a disposable fresh-stack run:

```sh
cp .env.example .env
WORKER_PROVIDER_MODE=stub docker compose up --build --detach
curl --fail --silent --show-error http://127.0.0.1:3000/api/health
make smoke
docker compose down --volumes --remove-orphans
```

The last command deletes this Compose project's data volumes. See the
[developer handoff](docs/CODEBASE_HANDOFF.md) before using it around data that
must be retained.

## What Phase 1 includes

- SvelteKit PWA and API/BFF
- PostgreSQL/pgvector canonical ledger and discriminated background jobs
- MinIO raw-statement storage using non-root application credentials
- Python/Polars ingestion worker
- Amex XLSX, generic CSV, OFX/QFX, and learned tabular adapters
- Deterministic PDF table extraction with a fail-closed `needs_ai` result
- Cached historical CAD/USD/TZS valuation with atomic base-currency switching
- Deterministic categorization rules, governed AI proposals, user overrides,
  deduplication, reconciliation, and coverage-gap reporting
- Account management, credit limits/utilization, net worth, and FX-fee analytics
- Dashboard, Transactions, Accounts, Categories, and Imports application routes
- Golden regression coverage for the reconciled closing balance `2855.59`

Checked-in fixtures and provider responses are synthetic. Sanitized
institution-specific TZS/USD exports have not yet been supplied or accepted, so
compatibility with a particular institution's CSV/XLSX layout remains pending.

## Documentation

Start with [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) for current scope,
[docs/PHASE-1-BUILD-PLAN.md](docs/PHASE-1-BUILD-PLAN.md) for active acceptance
criteria, [docs/BUILD-PLAN.md](docs/BUILD-PLAN.md) for the Phase 0 baseline, and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the longer-term system design.
For a developer handoff, use
[docs/CODEBASE_HANDOFF.md](docs/CODEBASE_HANDOFF.md). The `docs/` directory is
the source of truth.
