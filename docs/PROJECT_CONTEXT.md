# Ledger — Project Context

Current Phase: 0
Phase Status: in_review
Jira Epic: N/A
Confluence Space: N/A

## What This Is

Ledger is a self-hostable personal-finance application that imports bank
statements into one auditable canonical ledger. Financial values are parsed,
stored, reconciled, and aggregated with deterministic code. Phase 0 delivers a
working local vertical slice for American Express XLSX statements and generic
CSV files; AI integrations are represented only by an idle provider seam.

The detailed system design lives in [ARCHITECTURE.md](ARCHITECTURE.md), and the
implementation sequence and Phase 0 acceptance criteria live in
[BUILD-PLAN.md](BUILD-PLAN.md). The practical module and operations map for a
new maintainer is [CODEBASE_HANDOFF.md](CODEBASE_HANDOFF.md).

## Phase 0 Scope

Phase 0 is complete when the local stack can:

1. Start the web app, worker, PostgreSQL, and MinIO with Docker Compose.
2. Upload supported statement files and process them asynchronously.
3. Parse and normalize Amex XLSX and generic CSV transactions.
4. Deduplicate repeat or overlapping uploads.
5. Stamp CAD transactions at a deterministic 1:1 base-currency rate.
6. Reconcile statement opening balance plus transactions to closing balance.
7. Display accounts, running balance, cash flow, and searchable transactions.
8. Pass TypeScript checks, Python lint/type checks, and financial regression
   tests, including the golden closing balance of `2855.59`.

PDF parsing is deterministic-only in this phase. Unknown/irregular PDFs may be
reported as requiring AI, but no statement data is sent to an AI provider.

## Explicitly Out of Scope

- AI-assisted column mapping, extraction, or categorization
- Live bank connections
- Authentication and multi-tenant product flows
- Foreign-native account conversion and base-currency switching
- Advanced trends, anomaly detection, recurring detection, and forecasting
- Natural-language querying and result narration

## Technology Stack

| Area | Phase 0 choice |
|---|---|
| Web UI and BFF | SvelteKit, TypeScript, adapter-node |
| Shared contracts | TypeScript types and Zod schemas |
| Worker | Python 3.12, Polars, Pydantic, psycopg |
| Database and queue | PostgreSQL 16 with pgvector; plain ordered SQL migrations |
| Object storage | MinIO through the S3 API |
| Charts | uPlot for running balance; ECharts for cash flow |
| Local orchestration | Docker Compose and Make |
| Quality gates | TypeScript checking, Vitest, pytest, Ruff, mypy |

## Architecture

The SvelteKit service owns the browser UI and HTTP API. It stores uploads in
MinIO, writes ingest jobs to PostgreSQL, and serves parameterized ledger reads.
The Python worker claims queued jobs with row locking, fetches raw objects,
selects a deterministic adapter, normalizes and categorizes rows, inserts them
idempotently, reconciles each statement, and records the job result. PostgreSQL
is the source of truth; MinIO retains only application-encrypted source files.

## Canonical Phase 0 Data

The ordered SQL migrations define institutions, accounts, statements,
categories, merchants, transactions, jobs, adapters, and FX rates. Monetary
columns use fixed-precision numeric values. A transaction stores immutable
native amount/currency values alongside derived base-currency values and the
rate/date used. `dedup_hash` is unique and makes repeated ingestion safe.

Credit-card sign convention is fixed: charges and fees are positive; payments,
credits, and refunds are negative. Reconciliation uses:

`opening_balance + sum(amount_native) = closing_balance`

## Phase Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Ledger core, deterministic ingestion, basic dashboard | In review |
| 1 | Multi-bank mapping, multi-currency, category overrides | Not started |
| 2 | Deep analytics, anomalies, recurring detection | Not started |
| 3 | Grounded natural-language query layer | Not started |
| 4 | Ingestion hardening, offline polish, forecasts | Not started |

## Key Design Decisions

- Use a polyglot TypeScript/Python split because ingestion and analytics benefit
  from Python while UI and request orchestration benefit from shared TS types.
- Use plain ordered SQL migrations to keep the schema explicit and portable.
- Use PostgreSQL itself as the Phase 0 job queue; Redis is not required.
- Keep all financial arithmetic deterministic and independently testable.
- Treat CAD as the Phase 0 base currency; non-CAD rate lookup is deferred.
- Store only masked account references and sanitized test data.
- Encrypt raw statements before object storage with the versioned envelope in
  [ADR-0001](decisions/0001-application-layer-statement-encryption.md).

## Environment Variables

The committed `.env.example` is authoritative. It documents database,
object-storage, statement-encryption, service, base-currency, polling, and
optional future LLM configuration. Real `.env` files and credentials must never
be committed. Losing the production statement-encryption key makes stored raw
files unreadable.

## Working Agreements

- Stay within this Phase 0 scope unless the scope is explicitly changed.
- Update this document and the affected design document before implementing a
  scope deviation.
- Record material deviations in `docs/decisions/` and `CHANGELOG.md`.
- Never use an LLM for arithmetic or allow one to write directly to the ledger.
