# Changelog

All notable changes to Ledger are documented here.

## [Unreleased] — Phase 2

### Added

- [ADR-0007] Explicit Canada/Tanzania account scopes, a separate market
  profile, market-scoped analytics, and progressive transaction disclosure.
- [ADR-0008] Separately gated Phase 2.1 support for stable CAD/TZS home
  reporting with direct native recomputation, currency-fenced analytics
  publication, and frozen threshold profiles. Its implementation is present;
  approval remains separate from Phase 2.
- Ordered migrations `014` and `015` for explicit account markets, the market
  profile, scoped analytics identity, CAD/TZS threshold profiles, generalized
  reporting values, immutable home-currency switch auditing, currency-fenced
  publication, and refusal to roll back while TZS is active.
- Optional market filters across accounts, transactions, ordinary analytics,
  FX, and Insights, plus canonical transaction-detail conversion evidence.
- A shared All/Canada/Tanzania selector, single-amount Activity rows, responsive
  conversion drawer, simplified Home, Insights FX, Settings Advanced, `/more`,
  and four-item mobile navigation.

- [ADR-0005] Three-layer original/posted/reporting monetary truth, Stage 1 fixed
  public CAD reporting, deferred FX valuation, and deterministic materialized
  analytics with durable reviewed findings. ADR-0008 supersedes only the
  fixed-CAD clause for Phase 2.1.
- [ADR-0006] Versioned, bounded local-OCR acceptance for the supplied I&M Bank
  Tanzania TZS image-PDF layout, with institution-specific USD statements
  explicitly deferred.
- Phase 2 source-of-truth build plan covering multi-currency hardening, trends,
  seasonality, recurring activity, explainable findings, the Insights workflow,
  and explicit completion gates.
- Ordered migrations `012` and `013` for three-layer transaction money,
  deferred CAD valuation, fixed-CAD constraints, analytics generations,
  materialized monthly aggregates, recurring series, and durable findings.
- Exact-decimal shared Insights contracts, deterministic analytics primitives,
  the `analytics_refresh` job contract, and an `/insights` workflow for trends,
  recurring activity, findings evidence/review, settings, and rebuild controls.
- Deterministic conventional XLSX ingestion through `generic_xlsx_v1`, sharing
  the generic CSV rules for paired original money and explicit inline or
  standalone FX-fee evidence.
- An active synthetic Phase 2 smoke harness carrying forward the `2855.59` and
  zero-row repeat gates while covering separate USD/TZS accounts, three-layer
  money, explicit market scopes, CAD/TZS maintenance round trips, explicit FX
  fees, analytics refresh, and Insights review.
- The `im_bank_tz_pdf_v1` adapter, sanitized OCR-text regression fixtures, and
  `make im-bank-tz-acceptance` gate. The adapter cross-checks each local OCR
  amount with running-balance movement, printed totals, and the closing balance
  and accepts valid zero-activity statements without using an external model.

### Changed

- Reopened Phase 2 for ADR-0007 review remediation while keeping one repository,
  ledger, ingestion pipeline, and deterministic analytics engine, then returned
  it to `in_review` after the expanded gates passed.
- Moved balance/cash-flow exploration into Insights and analytics health,
  sensitivity, readiness, and rebuild controls into Settings Advanced.
- Advanced the active project phase to Phase 2, accepted the supplied I&M
  Tanzania TZS statements as its real-bank evidence, and deferred a named USD
  institution adapter under ADR-0006.
- Extended transaction ingestion and response contracts with original money,
  explicit FX-fee evidence, nullable reporting valuation, and `pending_fx`.
  Stage 1 fixed public reporting to CAD; ADR-0008 now governs the separate
  CAD/TZS maintenance workflow.
- Made incremental analytics refreshes rebuild changed monthly aggregate
  periods and copy unaffected rows, while recomputing recurrence and findings
  from full source history independently within `ALL`, `CA`, and `TZ`; full and
  incremental runs both publish atomically and expose their affected periods.
- Accepted RFC 3339 UTC-offset source watermarks in analytics job results so
  completed PostgreSQL-backed refreshes remain readable through the jobs API.
- Added Tesseract to the worker image for the named I&M Tanzania adapter and
  deferred a named real-USD institution adapter while retaining generic USD
  CSV/XLSX/OFX and three-layer contract coverage.

### Fixed

- Round derived base amounts to exact currency cents with half-up semantics
  before model validation, allowing valid high-magnitude TZS conversions such
  as `529973.00 TZS × 0.00054 = 286.19 CAD` without weakening exact-decimal
  validation.

### Verification checkpoint

- A disposable PostgreSQL run applied migrations `001`–`015` from empty and
  upgraded Phase 1 data without changing immutable native truth or inferring
  markets. It preserved legacy finding review state, exercised scoped
  materialization and market guards, proved CAD→TZS→CAD rebuilding and immutable
  switch auditing, fenced publication by active currency, passed
  rollback/reapplication, and refused rollback while TZS was active.
- `make benchmark-analytics` populated a disposable migrated database with
  exactly 100,000 synthetic transactions. The production full refresh completed
  in `16.385s` (limit `120s`) and its slowest warm materialized read in `1.721ms`
  (limit `1000ms`), then removed the temporary database.
- A uniquely named disposable fresh stack passed the active Phase 2 `make
  smoke` contract on rebuilt images and clean migrations `001`–`015` plus seed:
  the Phase 0 fixture reconciled to `2855.59` with six rows and zero on repeat;
  synthetic USD/TZS accounts covered explicit market scopes, both
  original/posted directions, CAD/TZS round trips, explicit FX evidence,
  analytics refresh, materialized Insights reads, and durable finding review.
  The named Compose project and volumes were removed without touching the
  default user stack. This synthetic evidence complements the real-bank gate.
- All 11 supplied sanitized I&M Tanzania TZS image-PDF statements matched
  `im_bank_tz_pdf_v1` and reconciled exactly, representing 41 transactions and
  five valid zero-activity statements. The largest 17-row statement added zero
  rows on repeat and remained `pending_fx` in the provider-free pipeline. A
  disposable encrypted upload through web, MinIO, worker, PostgreSQL, and the
  fixture FX provider added 17 rows, reconciled to `2994491.30 TZS`, valued all
  17 rows, and added zero rows on repeat; the disposable project was removed.
- The final automated checkpoint passed `make check` with zero Svelte
  errors/warnings, Ruff, and strict mypy across 32 source/script files; `make
  test` with 23 shared, 63 web-server, 7 component, 20 Playwright, and 196
  worker tests plus 1 intentional worker skip; and the `pnpm build` production
  build.
  With the real TZS gate accepted and named USD support deferred by ADR-0006,
  Phase 2 has advanced to `in_review`; closure still requires review approval.

## [Phase 1 — Multi-Bank and Multi-Currency] — 2026-07-24

### Added

- [ADR-0003] Privacy-minimized, structured AI categorization proposals with
  learned merchant mappings and protected user overrides.
- [ADR-0004] Native-currency credit limits, asset/liability account semantics,
  atomic base valuation, and deterministic net worth.
- Phase 1 local backlog and Phase 0 retrospective.
- Ordered migrations `006`–`011` for card-only credit limits, immutable funded
  account identity, singleton ledger settings, category archive/protection,
  transaction provenance, merchant/flow mappings, audited proposals,
  discriminated retryable jobs, the conditional categorization backfill,
  corrected fallback confidence, OFX-scoped FITID uniqueness, referenced
  category-kind immutability, and strict suffix-only masked account references.
- Account, institution, category, categorization proposal, transaction
  correction, settings, job-history, net-worth, FX-analysis, and expanded
  account-summary APIs with shared Zod contracts and exact decimal strings.
- An unresolved-merchant API and Categories-page workload view, separate from
  the audited low-confidence/new-category proposal queue.
- OFX1/OFX2 bank and card parsing, validated unknown CSV/XLSX AI mapping,
  minimized AI categorization, Frankfurter/cache/fixture FX providers, and
  `ingest`, `categorize`, `fx_refresh`, and `base_currency_rebuild` worker jobs.
- Focused Dashboard, Transactions, Accounts, Categories, and Imports routes
  under a responsive shared PWA shell.
- Component/browser/worker/contract test coverage and a synthetic Phase 1 smoke
  harness for the golden reconciliation, repeat idempotency, USD/TZS imports,
  categorization, utilization, net worth, FX analysis, and base switching.

### Changed

- Kept credit-card payments neutral in cash-flow net totals while exposing them
  as a separate chart series, so payment activity remains visible without
  double-counting the underlying card spending.
- Made account balances and cash flow account-kind-aware, preserved native
  positions beside derived base values, and excluded unverifiable accounts from
  net worth with explicit partial-state reasons. Non-null `ok`, `gap`, and
  one-sided `pending` reported balances may anchor positions; `mismatch`
  balances are excluded.
- Shared one validated `0..7`-day FX-staleness policy between worker providers
  and web reads, and returned per-row transaction running balances.
- Limited offline private-read caching to dashboard balance and cash-flow
  aggregates. Net worth, transactions, account lists, FX data, jobs, imports,
  category review data, and all writes remain uncached.

### Verification

- At Phase 1 closure, the recorded `make test`, `make check`, production web
  build, clean migration/seed, and disposable fresh-stack stub-provider smoke
  gates passed. The smoke preserved `2855.59`, proved zero-row repeat imports,
  and covered OFX1/OFX2/QFX, synthetic USD/TZS valuation, categorization,
  utilization, net worth, FX fees, and an atomic CAD-to-USD rebuild without
  mixed-base reads.
- Checked-in CAD/USD/TZS fixtures are synthetic. Institution-specific sanitized
  TZS/USD exports were not supplied or accepted in Phase 1. Phase 2 later
  accepted the supplied I&M Tanzania TZS statements and deferred a named USD
  adapter under ADR-0006.

## [Phase 0 — Ledger Core] — 2026-07-24

### Added

- Developer codebase handoff covering runtime flows, module ownership,
  invariants, extension paths, operations, and debugging.
- Executable Phase 0 pnpm/uv monorepo with SvelteKit, Python/Polars,
  PostgreSQL/pgvector, MinIO, Docker Compose, Make, and CI.
- Deterministic Amex XLSX, generic CSV, and PDF-table ingestion with exact-money
  validation, account-aware signs, fail-closed date/header ambiguity,
  categorization, deduplication, reconciliation, coverage-gap detection, and an
  idle LLM provider seam.
- Responsive installable dashboard with account summaries, running balance,
  account-kind-aware cash flow, searchable transactions, upload polling, and
  safe offline caching.
- Lease-fenced PostgreSQL jobs, per-file outcomes, stale-claim recovery, ordered
  migrations, idempotent seeds, and bucket-scoped object-store access.
- Shared TypeScript contracts, worker/web test suites, container health checks,
  and full-stack golden smoke coverage for `2855.59` and zero-row repeat imports.
- Repository, Docker, package, formatter, editor, secret, build-output, and raw
  financial-data ignore rules.
- [ADR-0001] Versioned application-layer AES-256-GCM encryption for raw
  statements, with content-addressed object identity.
- [ADR-0002] Accept equivalent Amex Description/Merchant columns while
  rejecting conflicting aliases, and include tracebacks in worker failure logs.

### Fixed

- Parse the real two-sheet Amex transaction export, including explicit billing
  periods, processed dates, masked account identity, and opening/closing totals
  from `Transaction Summary`; repeat imports refresh corrected statement
  and processed-date metadata without duplicating ledger rows or erasing a
  previously verified balance when a later parse is incomplete.
- Prevent stale account and analytics values immediately after imports, label
  transaction-only movement as net activity when balances are unavailable, and
  calculate running positions by processed-date end of day.
- Sort “Largest/Smallest amount” by magnitude and add direct page plus
  10/25/50/100 rows-per-page controls to the transaction table.
