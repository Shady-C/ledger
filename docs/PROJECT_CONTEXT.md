# Ledger — Project Context

Current Phase: 2
Phase Status: in_review
Jira Epic: N/A
Confluence Space: N/A

## What This Is

Ledger is a self-hostable personal-finance application that imports bank
statements into one auditable canonical ledger. Financial values are parsed,
stored, reconciled, converted, aggregated, and analyzed with deterministic
code. Phase 2 makes original, account-posted, and CAD-reporting money explicit
and adds materialized trends, recurring-series detection, and explainable
reviewable findings.

The detailed system design lives in [ARCHITECTURE.md](ARCHITECTURE.md). Preserve
[BUILD-PLAN.md](BUILD-PLAN.md) as the Phase 0 baseline and
[PHASE-1-BUILD-PLAN.md](PHASE-1-BUILD-PLAN.md) as the completed Phase 1 record.
The active backlog and acceptance gates live in
[PHASE-2-BUILD-PLAN.md](PHASE-2-BUILD-PLAN.md). The practical module and
operations map is [CODEBASE_HANDOFF.md](CODEBASE_HANDOFF.md).

## Phase 2 Scope

Phase 2 is complete when the local stack can:

1. Preserve every Phase 0/1 ingestion, idempotency, reconciliation, privacy,
   and security guarantee, including the `2855.59` closing balance.
2. Represent optional original purchase money, exact account-posted money, and
   nullable derived CAD reporting money without conflating the three layers.
3. Import a statement only into an account of the same posted currency, reject
   mixed posted currencies, and keep separate TZS and USD account balances.
4. Persist and reconcile valid native transactions when CAD rates are missing,
   report them as `pending_fx`, and backfill only derived valuation later.
5. Accept the supplied sanitized real I&M Tanzania TZS-account statements
   through a versioned institution adapter with exact reconciliation and
   zero-row repeat imports. Institution-specific USD statement acceptance is
   deferred by ADR-0006; generic USD ledger behavior remains covered.
6. Materialize deterministic trends, comparisons, seasonality, recurring
   activity, renewals, price changes, and explainable findings.
7. Preserve user recurring corrections and finding review state through
   incremental and full analytics refreshes.
8. Provide an accessible `/insights` workflow and a compact Dashboard summary
   while retaining exact decimal API contracts and explicit partial coverage.
9. Meet the regression, performance, production-build, clean-migration/seed,
   and disposable fresh-stack gates in the Phase 2 build plan.

Forecasting, natural-language querying, outbound notifications,
authentication/multi-user tenancy, irregular-PDF AI extraction, investments,
budgets, and manual assets or liabilities are outside Phase 2.

## Implementation State

Phase 1 completed on 2026-07-24. Its recorded integrated test, static-check,
production-build, clean migration/seed, and disposable fresh-stack synthetic
smoke gates passed. The Phase 1 implementation includes the multi-account data
model, four service-job kinds, OFX/QFX and validated tabular ingestion,
governed categorization, historical FX caching, account/net-worth analytics,
and five focused application routes.

Phase 2 is now `in_review`. Migrations `012` and `013`, the three-layer
worker/persistence paths, deterministic generic CSV/XLSX support, materialized
analytics worker, shared contracts, Insights APIs, `/insights` route, compact
transaction amount stack, and Dashboard integration are present in the working
tree. Incremental refreshes recompute monthly aggregates for source months
changed since the published watermark and copy unaffected monthly rows into the
new generation; recurring series and findings are deliberately recomputed over
the full ledger because their evidence can cross period boundaries. Full mode
rebuilds all derived data, and both modes publish one generation atomically.

The final automated synthetic verification checkpoint passes:

- `make check`: Svelte reports zero errors and zero warnings; Ruff passes; and
  strict mypy succeeds across 32 source/script files.
- `make test`: 22 shared-contract, 48 web-server, 7 component, 15 Playwright,
  and 185 worker tests pass, with 1 intentional worker skip.
- `pnpm build` completes the production web build.
- Disposable PostgreSQL acceptance applies migrations `001`–`013` from empty,
  upgrades Phase 1 data without changing posted/CAD values, backfills valid
  Amex original money, enforces currency constraints, accepts pending-CAD TZS
  truth, queues FX/analytics work, and rolls back/reapplies `012`/`013`.
- The disposable 100,000-transaction benchmark completes a production full
  analytics rebuild in `8.298s` against the `120s` limit; its slowest warm
  materialized read is `2.212ms` against the `1000ms` limit.
- A uniquely named isolated Compose project rebuilt the current images, applied
  clean migrations `001`–`013` plus the seed, and passed the Phase 2 `make
  smoke` contract: the Phase 0 statement reconciled to `2855.59` with six rows
  and zero on repeat; synthetic USD/TZS activity proved both three-layer flow
  directions, fixed CAD, explicit fee/markup evidence, analytics refresh,
  materialized Insights reads, and durable finding review. Its disposable
  project/volumes were removed, and the default user stack was untouched.

The supplied local acceptance set now covers eleven sanitized I&M Bank Tanzania
TZS image-PDF statements through `im_bank_tz_pdf_v1`. All eleven reconcile
exactly, representing 41 transactions and five valid zero-activity statements.
The largest statement contributes 17 rows on first import and zero on repeat;
the same file also passes the encrypted object-store, web, worker, PostgreSQL,
CAD-valuation, reconciliation, and idempotency path. The adapter uses bounded
local Tesseract OCR and validates every amount against running balances,
printed totals, and the closing balance before persistence.

ADR-0006 defers a named real-USD institution adapter until a sanitized sample is
supplied. Generic USD CSV/XLSX/OFX behavior and both original/posted currency
directions remain covered by deterministic synthetic tests. The supplied PDFs
remain local ignored inputs; only sanitized OCR-text derivatives are checked in.
With the real TZS and automated gates satisfied, Phase 2 is ready for review,
but it is not closed until review is approved.

## Technology Stack

| Area | Phase 2 choice |
|---|---|
| Web UI and BFF | SvelteKit, TypeScript, adapter-node |
| Shared contracts | TypeScript types and Zod schemas with exact decimal strings |
| Worker | Python 3.12, Polars, Pydantic, psycopg |
| Database and queue | PostgreSQL 16 with pgvector, ordered SQL migrations, and discriminated jobs |
| Object storage | MinIO through the S3 API |
| FX rates | Frankfurter v2 public or self-hosted API with PostgreSQL cache |
| AI provider | Provider seam with Anthropic structured outputs for bounded mapping/categorization only |
| Analytics | Deterministic Python/SQL materialization with durable reviewed findings |
| Charts | uPlot for dense series; ECharts for comparisons and Insights views |
| Local orchestration | Docker Compose and Make |
| Quality gates | TypeScript checking, Vitest, Playwright, pytest, Ruff, mypy, smoke and the disposable 100k analytics benchmark |

## Architecture

The SvelteKit service owns the browser UI and HTTP API. It stores encrypted
uploads in MinIO, writes jobs to PostgreSQL, and serves parameterized ledger and
Insights reads. In the Phase 2 implementation, the Python worker claims queued work
with row locking, selects or learns a validated adapter, normalizes and
persists native rows, reconciles statements, enriches available CAD valuation,
and materializes analytics. PostgreSQL remains the source of truth for ledger
rows, cached rates, analytics snapshots, finding review state, settings, and
run metadata.

The Phase 2 processing contract adds `analytics_refresh` after successful
ingestion, category/proposal or transaction corrections, and FX backfills. Its
incremental mode refreshes affected monthly periods and carries forward
unaffected aggregate rows; recurrence and finding detectors still evaluate the
ledger-wide evidence set. Full mode rebuilds all derived data. Jobs are
deduplicated, report their affected periods, and publish atomically so readers
do not observe a partial snapshot. Models may propose redacted mappings or
categories; no model computes money, statistics, recurring series, or findings.

## Canonical Phase 2 Data

A transaction has three separate monetary layers:

- `original_amount` and `original_currency` are optional immutable merchant
  evidence and must be present together.
- `amount_native` and `currency_native` are required immutable bank-posted
  account truth and drive reconciliation and deduplication.
- `amount_base`, `fx_rate`, and `fx_rate_date` are nullable derived CAD
  reporting values; missing eligible rates produce `pending_fx`.

`fx_fee_amount_native` represents an explicit inline fee already included in
the posted amount. `is_fx_fee` marks a standalone fee transaction. Original and
posted amounts use the same flow sign, and analytics use absolute magnitudes
where a conversion ratio is required. A transaction's valuation or analytics
enrichment never changes its posted identity.

Every account and statement has one posted currency. Reconciliation remains:

`opening_balance + sum(amount_native) = closing_balance`

CAD is the fixed public reporting lens for Phase 2. An internal base rebuild is
retained only for migration/recovery compatibility. Monthly aggregates,
recurring series/occurrences, findings, analytics settings, and analytics-run
metadata are durable derived state governed by ADR-0005.

## Phase Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Ledger core, deterministic ingestion, basic dashboard | Completed |
| 1 | Multi-bank, multi-currency, governed categorization, accounts, net worth | Completed 2026-07-24 |
| 2 | Three-layer money, real TZS acceptance, deep analytics and Insights | In review |
| 3 | Grounded natural-language query layer | Not started |
| 4 | Ingestion hardening, adapter review/schema evolution, offline polish, forecasts | Not started |

## Key Design Decisions

- Use a polyglot TypeScript/Python split because ingestion and analytics benefit
  from Python while UI and request orchestration benefit from shared TS types.
- Use ordered SQL migrations and PostgreSQL-backed jobs to keep schema, queues,
  and materialized analytics explicit and portable.
- Keep every financial and statistical calculation deterministic and
  independently testable.
- Preserve application-encrypted raw statements per
  [ADR-0001](decisions/0001-application-layer-statement-encryption.md).
- Minimize and validate AI categorization per
  [ADR-0003](decisions/0003-ai-categorization-proposals.md).
- Treat cards as liabilities and value imported-account net worth per
  [ADR-0004](decisions/0004-account-positions-and-net-worth.md).
- Preserve original, posted, and nullable CAD-reporting layers; defer missing
  valuations; and materialize durable deterministic insights per
  [ADR-0005](decisions/0005-three-layer-money-and-materialized-insights.md).
- Accept the supplied image-only I&M Tanzania TZS layout through bounded local
  OCR and exact ledger checks, while deferring named USD-statement acceptance,
  per
  [ADR-0006](decisions/0006-im-bank-tanzania-pdf-and-deferred-usd-acceptance.md).

## Environment and Data Safety

The committed `.env.example` is authoritative for database, object-storage,
statement encryption, services, FX endpoint/staleness, polling, and AI provider
configuration. CAD is the fixed Phase 2 public reporting currency, not a
user-switchable environment option. Real `.env` files and credentials must
never be committed. Losing the production statement-encryption key makes
stored raw files unreadable.

Store only masked account references and sanitized test data. Real statement
samples must be sanitized before they become fixtures. Minimize financial data
sent to external AI services; no model receives complete statements, balances,
analytics histories, or finding calculations.

## Working Agreements

- Stay within active Phase 2 scope unless the source-of-truth documents and
  phase metadata are explicitly changed.
- Record material deviations in `docs/decisions/`, update affected docs, and
  append `CHANGELOG.md` before implementation diverges.
- Never let an LLM perform arithmetic, statistics, or a direct ledger write.
- Add named bank adapters only from sanitized real fixtures and version each
  institution/export layout.
- Do not advance Phase 2 from review to complete until review is approved and
  every non-deferred acceptance gate remains green.
- `docs/` is canonical. Confluence is only a future publish target; Jira and
  Confluence are currently unconfigured.
