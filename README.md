# Ledger

Ledger is a self-hostable personal-finance ledger that imports statement files,
normalizes them into one canonical model, reconciles every statement with exact
decimal arithmetic, and presents balances, cash flow, and searchable
transactions in an installable web app.

Phase 1 completed on 2026-07-24. Phase 2 is now in review, adding explicit
original → posted/native → CAD transaction provenance and deterministic,
materialized Insights. Structured AI remains limited to proposals for unknown
tabular layouts and previously unseen merchants; a model never computes or
writes balances, FX values, reconciliation, statistics, or findings.

## Quick start

Requirements: Docker with Compose and Make.

```sh
cp .env.example .env
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). The fresh local stack
creates a sanitized Amex development account automatically, so you can upload
an Amex XLSX, conventional CSV or XLSX, OFX/QFX statement, a deterministically
extractable PDF, or the supported I&M Tanzania TZS image-PDF layout immediately.
MinIO's local console is available at
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
make benchmark-analytics  # run the disposable 100k Phase 2 analytics benchmark
make im-bank-tz-acceptance # validate local sanitized I&M Tanzania TZS PDFs
```

Local quality commands require Node.js 22+, pnpm 11, and uv. uv installs the
locked Python 3.12 worker environment from `services/worker/uv.lock`, so the
host's system Python is not used. The worker container includes Tesseract.
Running the I&M PDF adapter or its acceptance command directly on the host also
requires a `tesseract` executable (for example, `brew install tesseract` on
macOS or the distribution package on Linux).

The analytics benchmark requires the local PostgreSQL service. It creates and
drops only a uniquely prefixed `ledger_benchmark_*` disposable database; use
`LEDGER_BENCHMARK_ADMIN_URL` when the development server is not on the default
local URL.

The Phase 2 smoke test generates sanitized statements in memory,
preserves the Phase 0 closing balance of `2855.59`, verifies zero-row repeat
ingestion, and exercises synthetic USD/TZS accounts, three-layer money, fixed
CAD reporting, FX evidence, analytics refresh, and Insights review. It does not
read local statement PDFs. The separate `make im-bank-tz-acceptance` command
validates every sanitized `.pdf` under `output/pdf` without printing transaction
descriptions or account details.

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

## Completed Phase 1 baseline

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

Most checked-in fixtures and all provider responses are synthetic. Two
sanitized OCR-text derivatives exercise the I&M Tanzania TZS layout, while the
complete supplied PDFs remain ignored local inputs. The named adapter reconciles
all 11 supplied statements exactly and re-imports the largest 17-row statement
with zero additions. Institution-specific USD statement support is deferred;
generic USD CSV/XLSX/OFX and three-layer ledger behavior remain tested.

## Phase 2 review scope

The Phase 2 foundation is implemented in the current working tree, including
generic CSV/XLSX multi-currency evidence mapping, atomically materialized
analytics, Insights APIs/UI, and fixed-CAD transaction presentation. The phase
is `in_review`: automated test/check/build, database, 100,000-transaction
benchmark, fresh-stack smoke, and supplied I&M Tanzania TZS real-bank gates
have passed. Review approval is still required before closure.

- Three independent original, account-posted, and nullable CAD-reporting money
  layers with explicit actual FX fees and pending valuation.
- Single-currency accounts and statements, with separate TZS and USD accounts
  even when one bank groups them under one relationship.
- Fixed public CAD reporting and retryable booked-date FX enrichment that never
  blocks valid native reconciliation.
- Materialized trends, comparisons, seasonality, recurring activity, renewals,
  price changes, duplicates, anomalies, data-quality findings, and durable
  review state.
- An accessible `/insights` workflow and concise Dashboard summary.

See [docs/PHASE-2-BUILD-PLAN.md](docs/PHASE-2-BUILD-PLAN.md) for the sequenced
backlog and exact release gates. These bullets describe active scope, not a
claim that Phase 2 acceptance has passed.

## Documentation

Start with [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) for current scope,
[docs/PHASE-2-BUILD-PLAN.md](docs/PHASE-2-BUILD-PLAN.md) for active acceptance
criteria, [docs/PHASE-1-BUILD-PLAN.md](docs/PHASE-1-BUILD-PLAN.md) for the
completed prior phase, [docs/BUILD-PLAN.md](docs/BUILD-PLAN.md) for the Phase 0
baseline, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the longer-term
system design.
For a developer handoff, use
[docs/CODEBASE_HANDOFF.md](docs/CODEBASE_HANDOFF.md). The `docs/` directory is
the source of truth.
