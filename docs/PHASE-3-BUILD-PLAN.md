# Ledger — Phase 3 Build Plan

Current Phase: 3
Phase Status: in_progress
Jira Epic: N/A
Confluence Space: N/A

## Outcome

Phase 3 adds a read-only Ask workflow as the first tab in Insights. One bounded
planning call translates a natural-language question into at most three
validated query specifications. Deterministic parameterized reads execute
against one published analytics generation, and an optional tokenized
narration call can refer only to locally created opaque facts. Every answer
includes auditable evidence and a normalized query view. Questions, answers,
and conversation state are never persisted.

ADR-0011 adds one bounded ingestion exception to this Ask-focused phase:
deterministic local support for the known Wealthsimple chequing text-PDF
layout. It does not advance general unknown-PDF extraction, OCR/model fallback,
or mapping/review work from Phase 4.

[ADR-0009](decisions/0009-bounded-tokenized-grounded-ask.md) is the governing
Ask decision; [ADR-0010](decisions/0010-fail-closed-ask-freshness-and-local-clarification.md)
refines source freshness, local clarification, and semantic fail-closed
behavior. [ADR-0011](decisions/0011-wealthsimple-chequing-pdf-v1.md) governs the
targeted Wealthsimple adapter and truthful terminal import presentation. Phase
2 and the separately approved Phase 2.1 are completed historical baselines;
their regression, reconciliation, currency-fencing, privacy, and performance
guarantees remain permanent gates.

## Sequenced Backlog

1. Close and document Phase 2 and Phase 2.1 separately, publish ADR-0009, and
   move active phase metadata to Phase 3 `in_progress`.
2. Add strict, versioned shared contracts for `AskPlanV1`, supported query
   unions, prior context, response outcomes, evidence, display hints, and
   operational errors.
3. Add a TypeScript provider seam with live Anthropic and deterministic stub
   adapters, bounded planning/narration prompts, timeouts, cancellation, and
   concurrency control.
4. Resolve symbolic dates, market scope, home currency, and exact entity names
   locally; return bounded clarification candidates for missing or ambiguous
   entities and account/scope conflicts.
5. Compile the closed query catalog into parameterized SQL and execute one plan
   in a repeatable-read, read-only transaction pinned to one matching analytics
   generation and home currency.
6. Tokenize all database-derived facts, validate the structured narration
   segment tree, and fall back to deterministic local prose on any provider or
   reference-policy failure.
7. Add `GET /api/ask/status` and `POST /api/ask` with independent enablement,
   no-store responses, stable outcomes, structured evidence, and bounded
   operational errors.
8. Add Ask as the first/default Insights tab with disclosure, examples,
   submit/cancel/retry, clarification choices, tab-memory follow-ups, reset,
   evidence cards/tables/charts, drill-down links, and normalized-query
   inspection.
9. Add contract, database, privacy, provider-failure, component, browser,
   full-stack stub, adversarial, and performance coverage while preserving all
   earlier phase gates.
10. Add `wealthsimple_chequing_pdf_v1`, its sanitized deterministic fixtures,
    and truthful privacy-safe terminal import presentation without changing
    HTTP or database contracts.
11. Run the deterministic release suite and the one-time opt-in live Anthropic
    acceptance gate. Move Phase 3 to `in_review` only after every gate passes.

## Public Interfaces

### Ask plan

`AskPlanV1` is separate from URL-filter query schemas and is a strict union:

- `execute`: one to three query specs;
- `clarify`: one focused question and optional choices; or
- `unsupported`: a stable reason code plus capability guidance.

The closed datasets are:

- `aggregate`: spending, inflow, outflow, net cash flow, transaction count,
  valued count, and pending-FX count, grouped by total, month, account,
  category, or merchant, with optional previous-period or prior-year comparison;
- `seasonality`: existing month-of-year average/median spending and observation
  counts, preserving the 12-month sufficiency rule;
- `recurring`: status, cadence, direction, overdue state, expected amount,
  price changes, and bounded occurrence evidence;
- `findings`: count or list filtered by type, status, severity, and entity;
- `fx`: total cost, explicit fees, estimated markup, and missing-rate evidence;
  and
- `transactions`: at most 20 locally rendered posted/reporting evidence rows
  with drill-down identifiers.

One aggregate may filter by one account, category, or merchant. Filtering by
one entity dimension while grouping by another is invalid because the current
materialized rows do not encode those intersections.

Date selectors are current/previous month or quarter, year-to-date, previous
year, trailing 3/6/12/24 months, rolling 1–366 days, an absolute ISO range, or
all history. Previous-period comparison uses the immediately preceding equal
range. “Last N months” includes the current partial month; “last month,” “last
quarter,” and “last year” mean the previous completed calendar period.

Market defaults to the explicit active `ALL`, `CA`, or `TZ` request scope and
may be overridden by an explicit question. Account/scope conflicts clarify
rather than guess. Reporting values always use the active CAD or TZS home
currency; a question never switches that currency.

### HTTP

- `GET /api/ask/status` returns `{ enabled, available, reason }` without secret
  or model identifiers.
- `POST /api/ask` accepts a 1–500 character question, explicit market, validated
  IANA timezone, and at most three prior question/validated-plan pairs. A local
  entity clarification may instead include one strict opaque selection plus the
  previously validated execute plan; that path bypasses planning.
- HTTP 200 outcomes are `answered`, `clarification_required`, `unsupported`,
  and `no_data`.
- Operational failures are `400 invalid_request`, `429 ask_busy`, `502
  ask_planning_failed`, `503 ask_disabled`, `503 ask_provider_unavailable`,
  `503 analytics_rebuilding`, and `504 ask_timeout`.

An answered response includes structured answer blocks, normalized plan,
resolved ranges, typed evidence and table/chart hints, exact-decimal cells,
market, home currency, analytics generation, threshold policy, source
watermark, coverage, truncation, and freshness state. SQL, prompts, and provider
payloads are never returned.

## Targeted Wealthsimple PDF Exception

- `wealthsimple_chequing_pdf_v1` runs before the generic PDF-table fallback and
  matches only the known Wealthsimple chequing fingerprint for a CAD asset
  account. Positioned PDF text is parsed locally with `pdfplumber`; no OCR,
  external document service, or model receives PDF content.
- The adapter parses the statement period, masked account reference,
  opening/closing summary, repeated page headers, printed page counters,
  booked/posted dates, wrapped descriptions, Unicode negative signs, signed
  amounts, and running balances.
- It writes no financial rows unless dates are in range, every signed amount
  explains its running-balance transition, the transaction sum reconciles the
  opening and printed closing balances, the final running balance equals the
  summary, the printed page sequence matches the PDF page count, and no
  transaction-like content remains unparsed. Zero activity is valid only when
  opening equals closing and no transaction-like content exists.
- A fingerprint miss continues to the existing generic PDF fallback; a matched
  file with invalid or ambiguous financial evidence ends in a terminal
  non-success outcome. General unknown/irregular PDF extraction, OCR/model
  fallback, mapping approval, and schema-evolution replay remain Phase 4.
- Existing HTTP/database contracts stay unchanged. Successful job details use
  the existing `adapter` field; terminal `needs_ai` is presented as “Needs
  format support” or “Needs attention,” terminal `done`/`needs_ai` jobs omit
  retry counters, and content-addressed PDF keys render as privacy-safe labels
  such as `PDF statement · …c99`.

## Deterministic and Privacy Boundaries

- SQL structure comes only from code-owned enum switches. Dates, identifiers,
  terms, scope, and every user/provider value remain bound parameters.
- All queries in one plan run in one repeatable-read, read-only transaction
  against one matching analytics generation. Because mutable source/entity rows
  cannot reconstruct an older generation, any newer transaction, statement,
  account, category, or merchant state returns `analytics_rebuilding` before
  planning or execution rather than producing a mixed-generation answer.
- Analytics run-result metadata records the FX-rate watermark captured inside
  the worker snapshot. Ask preserves both source and rate cutoffs at PostgreSQL
  microsecond precision and refuses FX execution after newer mutable rate data
  appears, until a matching generation is published.
- Exact PostgreSQL numeric arithmetic and decimal-string responses are
  mandatory. JavaScript and models perform no financial calculations.
- Entity resolution uses local normalized exact matching. Zero or multiple
  matches return at most five local clarification choices. Database-derived
  choices carry opaque local tokens; selecting one keeps the original question
  unchanged, skips the planner, and revalidates the entity and scope locally.
- Planner input is limited to the question, local current date/timezone, scope,
  home currency, static catalog, and three prior questions/validated plans.
- A code-owned intent gate returns unsupported before database/provider work for
  canonical raw-SQL, write, forecast, advice, balance, and net-worth requests.
- Narrator input contains only request-local opaque fact references. Unknown
  references, numeric literals, currency/percentage syntax, or model-authored
  quantitative claims trigger deterministic fallback narration.
- Questions, plans, evidence, results, prose, and conversation state are not
  logged or persisted. Operational logs contain only request ID, disposition,
  model tier, durations, query count, and error code.
- One request has a 45-second budget, provider calls have 20-second limits and
  no automatic retry, and each web process permits two concurrent requests.

## Insights Experience

- Ask is the first/default `/insights` tab; existing Overview, Trends,
  Recurring, Findings, and FX behavior remains intact.
- Status loads independently and lazily so disabled or failed Ask cannot break
  deterministic Insights.
- The UI shows the external-provider disclosure, static examples, active scope
  and home currency, submit/cancel/retry, clarification choices, and “New
  conversation.”
- Browser-tab memory retains at most three questions and validated plans, never
  prior answers or evidence, and clears on reload, reset, market change, or
  home-currency change.
- Structured prose appears beside accessible metric cards, tables, line/bar
  charts, coverage/freshness warnings, and transaction/finding/recurring
  drill-down links.
- Query inspection shows the normalized DSL and resolved ranges, never SQL,
  prompts, or provider payloads.
- Rendering is text-safe, keyboard-accessible, responsive, reduced-motion
  aware, and no-store. Ask is excluded from service-worker caches.

## Environment and Operations

- `ASK_ENABLED=false` keeps Ask independently disabled by default.
- `ASK_PROVIDER_MODE=live|stub` defaults to `live` and selects Anthropic or
  deterministic fixtures; Ask remains unavailable while disabled.
- `ASK_PROVIDER_TIMEOUT_MS=20000` sets the provider-call limit; the request
  budget remains 45 seconds and model calls are never retried automatically.
- Live mode reuses the existing Anthropic API key and capable/cheap model
  settings; status responses never reveal their values or model identifiers.
- A missing or unusable live provider makes Ask unavailable without degrading
  imports, ledger reads, or existing Insights.
- No migration is added because Ask and its browser context are not persisted.

## Verification and Release Gates

- Strict contract tests cover every query union, hostile extra keys,
  unsupported filter/group combinations, context/query/row limits, symbolic
  dates, resolved ranges, and response disposition.
- Hand-calculated database tests cover every metric and grouping, comparisons,
  seasonality, recurring/findings/FX, transaction evidence, zero denominators,
  partial FX, CAD/TZS, All/CA/TZ, unassigned accounts, and one-generation reads.
- Security tests prove user/provider strings never enter SQL text and that SQL
  injection, prompt injection, forecasting, writes, advice, budgets,
  investments, balances, and net-worth questions fail closed.
- Recording-provider tests prove planner minimization and that narrator
  payloads contain no database values, labels, dates, identifiers,
  descriptions, histories, or raw evidence.
- Failure tests cover malformed/refused/truncated/timed-out provider output,
  fabricated references, disabled/missing configuration, concurrency,
  rebuilding, no-data, clarification, and deterministic narration fallback.
- Component and Playwright tests cover setup, submit/cancel/retry,
  clarification, follow-up/reset, evidence, query inspection, partial coverage,
  scope changes, responsiveness, and accessibility.
- Wealthsimple adapter tests use sanitized two-page derivatives and cover
  positive/negative amounts, Unicode minus, repeated headers, wrapped
  descriptions, masked-reference and CAD asset-account validation, zero
  activity, whole-page omission, fingerprint drift, malformed/ambiguous/missing
  content, out-of-period dates, and every running-balance and summary mismatch.
- Pipeline tests prove persistence and repeat-import idempotency; import UI
  tests prove truthful terminal-state copy, hidden terminal retry counters, and
  privacy-safe PDF labels without retaining original filenames.
- A fresh-stack stub-provider smoke covers aggregate comparison, category
  drivers, recurring/finding evidence, FX evidence, transaction drill-down, a
  scoped follow-up, and unsupported SQL/write/forecast questions.
- On 100,000 transactions, every warm deterministic Ask query completes within
  one second and a three-query plan within two seconds.
- `make check`, `make test`, the production build, clean migrations/seeds,
  Phase 2 database acceptance and analytics benchmark, `2855.59`, repeat
  ingestion, CAD/TZS switching, and fresh-stack smoke remain green.
- `make ask-live-acceptance` is the opt-in live Anthropic run for canonical and
  adversarial prompts. It is a one-time manual gate before Phase 3 can move to
  `in_review`; CI always uses deterministic stubs.
- The 2026-07-26 post-deployment acceptance queued a fresh job against the six
  retained encrypted Wealthsimple object keys while preserving the earlier
  terminal `needs_ai` job. All six statements reconciled to 76 imported rows;
  the identical repeat added zero rows and skipped all 76.

## Out of Scope

Forecasting, balances/net worth, import or reconciliation exploration,
financial advice, writes, saved history, feedback storage, streaming,
prompt/result caching, budgets, investments, authentication, and multi-user
tenancy remain outside Phase 3. The service remains loopback-bound, local,
single-user, and read-only.

General unknown-PDF extraction, OCR/model fallback beyond the existing named
I&M adapter, manual format mapping/review, and safe replay after schema
evolution remain Phase 4. ADR-0011's exact Wealthsimple layout is the only new
Phase 3 PDF exception.

## Current State

Phase 3 is `in_progress`. The contracts, executor, privacy boundary, API, UI,
deterministic unit/component/browser suites, production build, and performance
gate are implemented. The real-PostgreSQL executor matrix is wired into the
database CI job through `make test-ask-postgres`. Do not mark the phase
`in_review` until a fresh-stack stub smoke, the PostgreSQL gate, and the one-time
live Anthropic acceptance gate have all run successfully in their authorized
environments.

The ADR-0011 exception's deterministic adapter, pipeline, and import-UI coverage
passes. Its private post-deployment acceptance completed on 2026-07-26: a fresh
job against the retained encrypted objects imported 76 rows across six
reconciled statements, the identical repeat added zero rows and skipped all 76,
and the original terminal job was preserved for audit history. Phase 3 remains
`in_progress` for the Ask gates above.
