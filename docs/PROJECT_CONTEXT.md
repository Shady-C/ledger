# Ledger — Project Context

Current Phase: 1
Phase Status: in_review
Jira Epic: N/A
Confluence Space: N/A

## What This Is

Ledger is a self-hostable personal-finance application that imports bank
statements into one auditable canonical ledger. Financial values are parsed,
stored, reconciled, converted, and aggregated with deterministic code. Phase 1
extends the proven Phase 0 slice to multiple institutions, CAD/USD/TZS accounts,
governed AI categorization, account management, and focused application routes.

The detailed system design lives in [ARCHITECTURE.md](ARCHITECTURE.md), and the
implementation sequence and Phase 0 acceptance criteria live in
[BUILD-PLAN.md](BUILD-PLAN.md). The active Phase 1 backlog and acceptance gates
live in [PHASE-1-BUILD-PLAN.md](PHASE-1-BUILD-PLAN.md). The practical module and
operations map for a new maintainer is
[CODEBASE_HANDOFF.md](CODEBASE_HANDOFF.md).

## Phase 1 Scope

Phase 1 is complete when the local stack can:

1. Preserve every Phase 0 ingestion, idempotency, reconciliation, and security
   guarantee, including the golden closing balance of `2855.59`.
2. Create and edit bank and credit-card accounts with optional card limits.
3. Parse OFX/QFX and learn validated adapters for unknown CSV/XLSX layouts.
4. Stamp and cache historical CAD, USD, and TZS FX rates and switch the global
   reporting currency without changing native ledger truth.
5. Categorize novel merchants through minimized, structured AI proposals while
   preserving user overrides and requiring review for taxonomy changes.
6. Display deterministic credit utilization, asset/liability totals, partial
   valuation states, net worth, and FX-fee analytics.
7. Provide focused Dashboard, Transactions, Accounts, Categories, and Imports
   routes under one responsive PWA shell.
8. Pass shared-contract, API, worker, browser, lint, type, and fresh-stack smoke
   gates against sanitized CAD/USD/TZS fixtures.

PDF parsing remains deterministic-only. Unknown/irregular PDFs may be reported
as requiring AI, but Phase 1 never sends PDF or complete statement content to a
model.

## Implementation State

The current working tree contains the Phase 1 data model, worker services,
public contracts/APIs, and five-route client. On 2026-07-24, `make test`,
`make check`, the production web build, all 11 fresh migrations plus the seed,
and a disposable fresh-stack stub-provider `make smoke` passed. Phase 1 is now
ready for review.

Migrations `006` through `011` add the Phase 1 foundations: card-only credit
limits and funded-account identity immutability; the CAD-seeded singleton
setting; category archive/protection, provenance, merchant/flow mappings, and
audited proposals; four discriminated job kinds with active deduplication and
three retries; the conditional one-time categorization backfill; corrected
fallback confidence; account-scoped FITID uniqueness for OFX-enriched rows;
category-kind immutability once a category is structurally referenced; and a
database-enforced masked-label-plus-suffix account-reference format that rejects
full or formatted account/card numbers.

All checked-in financial fixtures and stub-provider results are synthetic.
Sanitized institution-specific TZS/USD exports have not yet been supplied or
accepted. Synthetic tests cover protocol, valuation, privacy, retry, and failure
behavior, but institution-specific CSV/XLSX compatibility remains a Phase 1
acceptance item.

## Explicitly Out of Scope

- Live bank connections
- Authentication and multi-tenant product flows
- Investment, loan, property, and other manual balance-sheet accounts
- AI extraction for irregular PDFs and local OCR/model fallback
- Advanced trends, anomaly detection, recurring detection, and forecasting
- Natural-language querying and result narration
- Vector-similarity categorization

## Technology Stack

| Area | Phase 1 choice |
|---|---|
| Web UI and BFF | SvelteKit, TypeScript, adapter-node |
| Shared contracts | TypeScript types and Zod schemas |
| Worker | Python 3.12, Polars, Pydantic, psycopg |
| Database and queue | PostgreSQL 16 with pgvector; migrations `001`–`011` and discriminated jobs |
| Object storage | MinIO through the S3 API |
| FX rates | Frankfurter v2 public or self-hosted API with PostgreSQL cache |
| AI provider | Provider seam with Anthropic structured outputs first |
| Charts | uPlot for running balance; ECharts for cash flow |
| Local orchestration | Docker Compose and Make |
| Quality gates | TypeScript checking, Vitest, pytest, Ruff, mypy |

## Architecture

The SvelteKit service owns the browser UI and HTTP API. It stores uploads in
MinIO, writes ingest jobs to PostgreSQL, and serves parameterized ledger reads.
The Python worker claims queued jobs with row locking, fetches raw objects,
selects or learns a validated adapter, normalizes and FX-stamps rows, applies
deterministic enrichment, inserts them idempotently, reconciles each statement,
and records the job result. Separate jobs enrich unknown merchants and rebuild
derived base values. PostgreSQL is the source of truth; MinIO retains only
application-encrypted source files.

## Canonical Phase 1 Data

The ordered SQL migrations define institutions, accounts, statements,
categories, merchants, transactions, jobs, adapters, and FX rates. Monetary
columns use fixed-precision numeric values. A transaction stores immutable
native amount/currency values alongside derived base-currency values and the
rate/date used. `dedup_hash` is unique and makes repeated ingestion safe.

Accounts carry kind, native currency, optional masked reference, and an optional
native-currency credit limit for cards. Transactions record category provenance
and confidence; merchant/flow mappings and audited proposals carry learned AI
state. A single settings row stores the active reporting currency. Derived base
amounts can be rebuilt, while native values remain immutable.

Credit-card sign convention remains fixed: charges and fees are positive;
payments, credits, and refunds are negative. Reconciliation uses:

`opening_balance + sum(amount_native) = closing_balance`

## Phase Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Ledger core, deterministic ingestion, basic dashboard | Completed |
| 1 | Multi-bank, multi-currency, governed categorization, accounts, net worth | In review |
| 2 | Deep analytics, anomalies, recurring detection | Not started |
| 3 | Grounded natural-language query layer | Not started |
| 4 | Ingestion hardening, offline polish, forecasts | Not started |

## Key Design Decisions

- Use a polyglot TypeScript/Python split because ingestion and analytics benefit
  from Python while UI and request orchestration benefit from shared TS types.
- Use plain ordered SQL migrations to keep the schema explicit and portable.
- Use PostgreSQL itself for the Phase 1 discriminated job queue; Redis is not
  required at this scale.
- Keep all financial arithmetic deterministic and independently testable.
- Seed CAD as the reporting currency, cache dated provider rates for every
  non-identity conversion, and change the active base only after an atomic
  rebuild succeeds.
- Store only masked account references and sanitized test data.
- Encrypt raw statements before object storage with the versioned envelope in
  [ADR-0001](decisions/0001-application-layer-statement-encryption.md).
- Minimize and validate every AI categorization proposal as recorded in
  [ADR-0003](decisions/0003-ai-categorization-proposals.md).
- Treat card balances as liabilities and value net worth deterministically as
  recorded in [ADR-0004](decisions/0004-account-positions-and-net-worth.md).

## Environment Variables

The committed `.env.example` is authoritative. It documents database,
object-storage, statement-encryption, service, FX endpoint/staleness, polling,
and Anthropic provider configuration. CAD is the initial database setting, not
a permanently fixed environment-only value. Real `.env` files and credentials
must never be committed. Losing the production statement-encryption key makes
stored raw files unreadable.

## Working Agreements

- Stay within the active Phase 1 scope unless the scope is explicitly changed.
- Update this document and the affected design document before implementing a
  scope deviation.
- Record material deviations in `docs/decisions/` and `CHANGELOG.md`.
- Never use an LLM for arithmetic or allow one to write directly to the ledger.
