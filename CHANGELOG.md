# Changelog

All notable changes to Ledger are documented here.

## [Unreleased] — Phase 1

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

- Phase 1 is `in_review`: `make test`, `make check`, the production web build,
  and a disposable fresh-stack stub-provider `make smoke` all pass. The smoke
  preserves `2855.59`, proves zero-row repeat imports, and covers OFX1/OFX2/QFX,
  USD/TZS valuation, categorization, utilization/net worth, FX fees, and an
  atomic CAD-to-USD rebuild without mixed-base reads.
- Checked-in CAD/USD/TZS fixtures are synthetic. Institution-specific sanitized
  TZS/USD export acceptance remains pending user-supplied samples.

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
