# Ledger — Project Context

Current Phase: 3
Phase Status: in_progress
Jira Epic: N/A
Confluence Space: N/A

## What This Is

Ledger is a self-hostable personal-finance application that imports bank
statements into one auditable canonical ledger. Financial values are parsed,
stored, reconciled, converted, aggregated, queried, and analyzed with
deterministic code. Phase 3 adds a bounded natural-language Ask workflow over
the completed market-scoped analytics without allowing a model to inspect the
database, generate SQL, or calculate money.
ADR-0011 also permits one targeted Phase 3 ingestion exception: deterministic,
local support for the known Wealthsimple chequing text-PDF layout. It does not
bring general unknown-PDF extraction or mapping into Phase 3.

The detailed system design lives in [ARCHITECTURE.md](ARCHITECTURE.md). Preserve
[BUILD-PLAN.md](BUILD-PLAN.md) as the Phase 0 baseline,
[PHASE-1-BUILD-PLAN.md](PHASE-1-BUILD-PLAN.md) as the completed Phase 1 record,
and [PHASE-2-BUILD-PLAN.md](PHASE-2-BUILD-PLAN.md) as the completed Phase 2/2.1
record. The active backlog and acceptance gates live in
[PHASE-3-BUILD-PLAN.md](PHASE-3-BUILD-PLAN.md). The practical module and
operations map is [CODEBASE_HANDOFF.md](CODEBASE_HANDOFF.md).

## Phase 3 Scope

Phase 3 is complete when the local stack can:

1. Preserve every Phase 0–2.1 ingestion, idempotency, reconciliation,
   home-currency, analytics, privacy, and security guarantee, including the
   `2855.59` closing balance.
2. Translate one 1–500 character question into a strict `AskPlanV1` execute,
   clarify, or unsupported outcome with no more than three closed-catalog
   queries.
3. Resolve dates, scope, currency, and entities locally and execute only
   code-owned parameterized SQL in one read-only, repeatable-read transaction
   pinned to one analytics generation; reject mutable source/entity state newer
   than that generation.
4. Answer supported aggregate, seasonality, recurring, finding, FX, and
   transaction-evidence questions with exact-decimal values and explicit
   coverage, truncation, watermark, and freshness metadata.
5. Give the planner no schema, SQL, rows, results, or entity catalogs and give
   the optional narrator only request-local opaque fact references. Local entity
   clarification labels use server-resolved tokens and never re-enter the
   planner question.
6. Fall back to deterministic narration whenever provider output is malformed,
   refuses, times out, invents a reference, or contains a numeric, currency, or
   percentage literal.
7. Add Ask as the first/default Insights tab without degrading deterministic
   Insights when Ask is disabled or unavailable, and keep no persistent chat
   or answer history.
8. Meet the contract, database, privacy, adversarial, accessibility,
   regression, performance, fresh-stack stub, and one-time live-provider gates
   in the Phase 3 build plan.
9. Parse the exact Wealthsimple chequing PDF v1 layout locally for CAD asset
   accounts, fail closed on any page-sequence, date, row, running-balance, or
   printed-summary inconsistency, and meet the six-file/76-row plus
   zero-row-repeat acceptance target before recording that private replay as
   passed.

Forecasting, balances/net worth questions, import or reconciliation
exploration, advice, writes, saved history, streaming, prompt/result caching,
outbound notifications, authentication/multi-user tenancy, general unknown-PDF
extraction or mapping, OCR/model fallbacks beyond the existing named I&M
adapter, investments, budgets, and manual assets or liabilities are outside
Phase 3.

## Implementation State

Phase 1 completed on 2026-07-24. Phase 2 and its separately approved Phase 2.1
follow-up completed on 2026-07-25 after the permanent Phase 0–2.1 regression
gates were rerun and the recorded review evidence was accepted. Phase 2
delivered three-layer money, deferred valuation, deterministic materialized
analytics, explicit All/Canada/Tanzania scopes, progressive conversion
evidence, deep Insights, and the accepted I&M Tanzania TZS adapter. Phase 2.1
separately delivered stable CAD/TZS home reporting, direct native
recomputation, frozen materiality profiles, and currency-fenced analytics
publication under ADR-0008.

The Phase 2/2.1 closure evidence includes:

- `make check`: Svelte reports zero errors and zero warnings; Ruff passes; and
  strict mypy succeeds across 32 source/script files.
- `make test`: 23 shared-contract, 63 web-server, 7 component, 20 Playwright,
  and 196 worker tests pass, with 1 intentional worker skip.
- `pnpm build` completes the production web build.
- Disposable PostgreSQL acceptance applies migrations `001`–`015` from empty,
  upgrades Phase 1 data without inferring account markets or changing native
  truth, preserves legacy review state, exercises scoped materialization and
  market-reassignment guards, proves CAD→TZS→CAD rebuilding and immutable switch
  auditing, fences analytics publication by currency, rolls back/reapplies the
  upgrade path, and refuses rollback while TZS is active.
- The disposable 100,000-transaction benchmark completes a production full
  analytics rebuild in `16.385s` against the `120s` limit; its slowest warm
  materialized read is `1.721ms` against the `1000ms` limit.
- A uniquely named isolated Compose project rebuilt the current images, applied
  clean migrations `001`–`015` plus the seed, and passed the Phase 2 `make
  smoke` contract: the Phase 0 statement reconciled to `2855.59` with six rows
  and zero on repeat; synthetic USD/TZS activity proved explicit market scopes,
  both three-layer flow directions, CAD/TZS round trips, explicit fee/markup
  evidence, analytics refresh, materialized Insights reads, and durable finding
  review. Its disposable project/volumes were removed, and the default user
  stack was untouched.

The supplied local acceptance set covers eleven sanitized I&M Bank Tanzania
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
The real TZS and expanded automated gates remained satisfied through closure.

Phase 3 is now `in_progress`. ADR-0009 replaces the earlier iterative-agent
sketch with a bounded `AskPlanV1` planner, a closed deterministic executor, and
an optional tokenized narrator. ADR-0010 adds fail-closed mutable-source
freshness, local-only entity clarification, and code-owned prohibited-intent
enforcement. No schema migration is planned because Ask state is not persisted.
The implementation must remain `in_progress` until all Phase 3 deterministic
gates and the one-time live Anthropic acceptance gate pass.

ADR-0011 separately accepts `wealthsimple_chequing_pdf_v1` as a narrow Phase 3
exception. The adapter recognizes the known Wealthsimple chequing fingerprint,
requires a CAD asset account, reads positioned PDF text locally without OCR or
an external model, and validates the printed page sequence, every
running-balance transition, and the opening/closing summary before persistence.
The six private source PDFs remain
outside version control. On 2026-07-26, a fresh job using their retained
encrypted object keys imported 76 rows across six reconciled statements; the
identical repeat added zero rows and skipped all 76 existing transactions while
the original terminal job remained intact for audit history. General
unknown-PDF support remains Phase 4.

## Technology Stack

| Area | Phase 3 choice |
|---|---|
| Web UI and BFF | SvelteKit, TypeScript, adapter-node |
| Shared contracts | TypeScript types and Zod schemas with exact decimal strings |
| Worker | Python 3.12, Polars, Pydantic, psycopg |
| Database and queue | PostgreSQL 16 with pgvector, ordered SQL migrations, and discriminated jobs |
| Object storage | MinIO through the S3 API |
| FX rates | Frankfurter v2 public or self-hosted API with PostgreSQL cache |
| AI provider | Anthropic behind worker and TypeScript provider seams; deterministic stub modes for tests |
| Ask | Bounded synchronous planner, closed deterministic query executor, opaque-reference narrator |
| Analytics | Deterministic Python/SQL materialization with durable reviewed findings |
| Charts | uPlot for dense series; ECharts for comparisons and Insights views |
| Local orchestration | Docker Compose and Make |
| Quality gates | TypeScript checking, Vitest, Playwright, pytest, Ruff, mypy, smoke and the disposable 100k analytics/Ask benchmark |

## Architecture

The SvelteKit service owns the browser UI and HTTP API. It stores encrypted
uploads in MinIO, writes jobs to PostgreSQL, and serves parameterized ledger,
Insights, and Phase 3 Ask reads. The Python worker claims queued work
with row locking, selects or learns a validated adapter, normalizes and
persists native rows, reconciles statements, enriches available reporting valuation,
and materializes analytics. PostgreSQL remains the source of truth for ledger
rows, cached rates, analytics snapshots, finding review state, settings, and
run metadata. Ask remains synchronous in SvelteKit and stores no question,
plan, result, or conversation state.

The Phase 2 processing contract adds `analytics_refresh` after successful
ingestion, category/proposal or transaction corrections, and FX backfills. Its
incremental mode refreshes affected monthly periods and carries forward
unaffected aggregate rows; recurrence and finding detectors evaluate full
source history independently within `ALL`, `CA`, and `TZ`. Full mode rebuilds
all derived data. Jobs are
deduplicated, report their affected periods, and publish atomically so readers
do not observe a partial snapshot. Models may propose redacted mappings or
categories; no model computes money, statistics, recurring series, or findings.

## Canonical Ledger and Analytics Data

A transaction has three separate monetary layers:

- `original_amount` and `original_currency` are optional immutable merchant
  evidence and must be present together.
- `amount_native` and `currency_native` are required immutable bank-posted
  account truth and drive reconciliation and deduplication.
- `amount_base`, `fx_rate`, and `fx_rate_date` are nullable derived home-currency
  reporting values; missing eligible rates produce `pending_fx`.

`fx_fee_amount_native` represents an explicit inline fee already included in
the posted amount. `is_fx_fee` marks a standalone fee transaction. Original and
posted amounts use the same flow sign, and analytics use absolute magnitudes
where a conversion ratio is required. A transaction's valuation or analytics
enrichment never changes its posted identity.

Every account and statement has one posted currency. Reconciliation remains:

`opening_balance + sum(amount_native) = closing_balance`

Stage 1 retains CAD as the reporting lens while adding independent market
scopes. Phase 2.1 supports stable CAD or TZS home reporting; a switch is an
explicit Advanced maintenance operation, never a market-selector action.
Monthly aggregates,
recurring series/occurrences, findings, analytics settings, and analytics-run
metadata are durable derived state governed by ADR-0005 and ADR-0008. Every
generation is bound to its home currency and frozen threshold-policy version.

## Phase Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Ledger core, deterministic ingestion, basic dashboard | Completed |
| 1 | Multi-bank, multi-currency, governed categorization, accounts, net worth | Completed 2026-07-24 |
| 2 | Three-layer money, real TZS acceptance, market-scoped UX, deep analytics and Insights | Completed 2026-07-25 |
| 2.1 | Stable CAD/TZS home reporting and currency-fenced analytics rebuilds | Completed separately 2026-07-25 |
| 3 | Bounded grounded Ask workflow plus the targeted Wealthsimple PDF v1 exception | In progress |
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
- Preserve original, posted, and nullable reporting layers; defer missing
  valuations; and materialize durable deterministic insights per ADR-0005.
  ADR-0008 supersedes only ADR-0005's Stage 1 fixed-CAD clause and supports
  stable CAD/TZS home reporting through the maintenance workflow.
- Accept the supplied image-only I&M Tanzania TZS layout through bounded local
  OCR and exact ledger checks, while deferring named USD-statement acceptance,
  per
  [ADR-0006](decisions/0006-im-bank-tanzania-pdf-and-deferred-usd-acceptance.md).
- Keep one product and engine; model account markets separately from the
  ledger-level market profile and reporting currency per
  [ADR-0007](decisions/0007-market-scopes-and-progressive-disclosure.md).
- Support only CAD and TZS as stable home currencies, rebuilding reporting
  values from immutable native money and fencing analytics publication per
  [ADR-0008](decisions/0008-configurable-cad-tzs-home-currency.md).
- Use one bounded, validated Ask plan; execute only code-owned parameterized
  reads; and expose database facts to narration only as request-local opaque
  references per
  [ADR-0009](decisions/0009-bounded-tokenized-grounded-ask.md).
- Fail closed on mutable source drift and keep database-derived clarification
  selections outside provider payloads per
  [ADR-0010](decisions/0010-fail-closed-ask-freshness-and-local-clarification.md).
- Accept only the known Wealthsimple chequing text-PDF layout through local
  positioned-text parsing and exact running-balance/summary checks, while
  preserving general PDF extraction for Phase 4, per
  [ADR-0011](decisions/0011-wealthsimple-chequing-pdf-v1.md).

## Environment and Data Safety

The committed `.env.example` is authoritative for database, object-storage,
statement encryption, services, FX endpoint/staleness, polling, worker AI, and
Ask provider configuration. `ASK_ENABLED=false` is the independent default;
`ASK_PROVIDER_MODE=live|stub` defaults to live Anthropic or selects deterministic
fixtures while reusing the existing Anthropic key and capable/cheap model
settings. `ASK_PROVIDER_TIMEOUT_MS=20000` bounds each provider call. Home
currency is persisted ledger state and may be changed only
through the confirmed Advanced maintenance workflow. Real `.env` files and credentials must
never be committed. Losing the production statement-encryption key makes
stored raw files unreadable.

Store only masked account references and sanitized test data. Real statement
samples must be sanitized before they become fixtures. Ask's planner receives
no schema, SQL, rows, results, or entity catalog, and its narrator receives
only opaque fact references. No model receives complete statements, balances,
analytics histories, raw transaction evidence, or finding calculations.
Private Wealthsimple acceptance PDFs remain ignored local inputs; only
sanitized layout derivatives may be committed. Their content is parsed locally
and is never sent to a model or external document service.

## Working Agreements

- Stay within active Phase 3 scope unless the source-of-truth documents and
  phase metadata are explicitly changed.
- Record material deviations in `docs/decisions/`, update affected docs, and
  append `CHANGELOG.md` before implementation diverges.
- Never let an LLM perform arithmetic, statistics, or a direct ledger write.
- Add named bank adapters only from sanitized real fixtures and version each
  institution/export layout.
- Do not advance Phase 3 to `in_review` until every deterministic acceptance
  gate and the one-time live Anthropic acceptance run pass.
- `docs/` is canonical. Confluence is only a future publish target; Jira and
  Confluence are currently unconfigured.
