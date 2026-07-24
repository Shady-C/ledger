# Ledger

Ledger is a self-hostable personal-finance ledger that imports statement files,
normalizes them into one canonical model, reconciles every statement with exact
decimal arithmetic, and presents balances, cash flow, and searchable
transactions in an installable web app.

Phase 0 is deterministic by design: no AI service participates in parsing,
categorization, reconciliation, or financial math.

## Quick start

Requirements: Docker with Compose and Make.

```sh
cp .env.example .env
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). The fresh local stack
creates a sanitized Amex development account automatically, so you can upload
an Amex XLSX, a conventional CSV statement, or a deterministically extractable
PDF immediately. MinIO's local console is available at
[http://localhost:9001](http://localhost:9001).

The values in `.env.example` are development defaults only. Replace every
password before exposing the stack beyond your own machine, and never commit a
real `.env` file or statement data. Replace and securely back up
`STATEMENT_ENCRYPTION_KEY` as well: losing that key makes stored raw statements
unreadable.

## Common commands

```sh
make up          # build and run the complete stack
make down        # stop it without deleting data volumes
make migrate     # apply ordered SQL migrations
make seed        # load the idempotent Phase 0 reference data
make test        # run TypeScript and Python tests
make check       # typecheck TypeScript; lint and typecheck Python
make smoke       # run the golden API flow against a healthy fresh stack
```

Local quality commands require Node.js 22+, pnpm 11, and uv. uv installs the
locked Python 3.12 worker environment from `services/worker/uv.lock`, so the
host's system Python is not used.

The smoke test generates sanitized Amex-shaped workbooks in memory, verifies a
reconciled closing balance of `2855.59`, checks monthly cash flow, and verifies
an identical second upload adds zero transactions. It does not read or persist
private test fixtures.

## What Phase 0 includes

- SvelteKit PWA and API/BFF
- PostgreSQL/pgvector canonical ledger and job queue
- MinIO raw-statement storage using non-root application credentials
- Python/Polars ingestion worker
- Amex XLSX and generic CSV adapters
- Deterministic PDF table extraction with a fail-closed `needs_ai` result
- Exact CAD stamping, categorization rules, deduplication, reconciliation, and
  coverage-gap reporting
- Running balance and cash-flow charts plus searchable/paginated transactions
- Golden regression coverage for the reconciled closing balance `2855.59`

## Documentation

Start with [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) for current scope,
[docs/BUILD-PLAN.md](docs/BUILD-PLAN.md) for Phase 0 acceptance criteria, and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the longer-term system design.
For a developer handoff, use
[docs/CODEBASE_HANDOFF.md](docs/CODEBASE_HANDOFF.md). The `docs/` directory is
the source of truth.
