# Changelog

All notable changes to Ledger are documented here.

## [Unreleased] — Phase 0

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
