# Project Process

## Phase 0 Retrospective — Ledger Core

**Completed:** 2026-07-24

Phase 0 delivered the executable local stack, deterministic Amex XLSX and
generic CSV ingestion, PDF table parsing, encrypted statement storage,
idempotent persistence, reconciliation, basic analytics, and the original
single-page PWA dashboard.

### What Went Well

- Exact-money and account-aware sign rules were established before broadening
  institution support.
- Golden reconciliation and repeat-import tests caught financial regressions.
- The worker, API, and shared-contract seams leave room for Phase 1 without
  replacing the canonical ledger.
- Raw statement encryption and masked account validation were implemented in
  the first executable slice.

### What Could Improve

- Account and job contracts were initially shaped around one seeded card and
  one job kind.
- The dashboard accumulated unrelated workflows on one route.
- Category provenance and learned mappings should have been first-class from
  the initial schema.
- Mixed asset/liability and multi-currency consolidation semantics needed to be
  explicit earlier.

### Decisions and Carry-Forward

- ADR-0001 and ADR-0002 remain the Phase 0 decisions.
- Phase 1 starts with ADR-0003 and ADR-0004.
- The Phase 0 golden closing balance and zero-row repeat-import guarantees are
  permanent regression gates.

## Phase 1 Retrospective — Multi-Bank and Multi-Currency

**Completed:** 2026-07-24

The completed backlog and acceptance record live in
[PHASE-1-BUILD-PLAN.md](PHASE-1-BUILD-PLAN.md). The plan remains the historical
scope baseline.

### Delivered

- Multi-account institution and account management with card limits,
  account-kind-aware positions, utilization, and deterministic net worth.
- OFX/QFX parsing, validated learned CSV/XLSX mappings, governed categorization,
  and reviewable user overrides.
- Historical CAD/USD/TZS rate caching, partial valuation states, FX analysis,
  and atomic reporting-currency rebuild infrastructure.
- Focused Dashboard, Transactions, Accounts, Categories, and Imports routes.

### What Went Well

- Phase 0 reconciliation and repeat-import invariants stayed permanent gates
  while the schema and worker expanded.
- Financial arithmetic, category precedence, AI privacy boundaries, and
  provider-failure isolation remained explicit and testable.
- Exact-money contracts and a shared FX staleness policy kept web and worker
  behavior aligned.
- Splitting the application into focused routes reduced workflow congestion
  without changing the canonical ledger.

### What Could Improve

- Original purchase currency remained format-specific enrichment instead of a
  first-class monetary layer.
- Requiring reporting valuation during import coupled native ledger acceptance
  too tightly to external FX availability.
- Switchable public base currency complicated consistent longitudinal
  analytics; Phase 2 Stage 1 fixed the reporting lens to CAD. ADR-0008 later
  replaces only that fixed-CAD clause with a separately gated, confirmed
  CAD/TZS maintenance workflow.
- Synthetic TZS/USD fixtures prove protocol and arithmetic behavior but cannot
  prove compatibility with real institution export layouts.

### Decisions and Carry-Forward

- ADR-0003 and ADR-0004 remain the Phase 1 decisions.
- ADR-0005 begins Phase 2 with three-layer monetary truth, deferred CAD
  valuation, and deterministic materialized insights. ADR-0008 later supersedes
  only its fixed-CAD clause and ADR-0004's public-switching semantics.
- The golden `2855.59` closing balance and zero-row repeat import remain
  permanent regression gates.
- The initial carry-forward required sanitized real TZS and USD institution
  statements to reconcile and re-import idempotently. ADR-0006 later accepts
  the supplied real TZS evidence and defers institution-specific USD support.

### Closure Evidence — 2026-07-24

The recorded integrated test, static-check, production-build, clean-migration,
and disposable fresh-stack smoke gates passed. All checked-in
protocol/failure fixtures and provider responses were synthetic. No sanitized
institution-specific TZS/USD export was supplied or accepted during Phase 1.

## Phase 2 Process

The active sequenced backlog, exact behavioral criteria, performance targets,
and review state live in
[PHASE-2-BUILD-PLAN.md](PHASE-2-BUILD-PLAN.md). Phase 2 is `in_review` after the
ADR-0007 market-scoped UX remediation passed its expanded gates. ADR-0008's
CAD/TZS home-currency implementation is present and verified, but Phase 2.1
remains a separate, unapproved gate and does not become approved with Phase 2.

The final automated checkpoint passes `make check`, with zero Svelte errors or
warnings plus Ruff and strict mypy, and `make test`, with 23 shared-contract, 63
web-server, 7 component, 20 Playwright, and 196 worker tests plus 1 intentional
worker skip. The production web build also passes. Disposable PostgreSQL
acceptance applies all 15 migrations (`001`–`015`) and covers the Phase 1
upgrade, market assignment/profile behavior, scoped analytics identity,
currency-fenced publication, the immutable home-currency switch audit, and safe
rollback behavior.

The disposable 100,000-transaction production analytics rebuild completes in
`16.385s` against the `120s` limit; its slowest warmed materialized read is
`1.721ms` against the `1000ms` limit. A uniquely named clean Compose stack also
rebuilt the current images, applied all migrations plus the idempotent seed, and
passed the active smoke contract, including the `2855.59` closing balance,
zero-row repeat ingestion, All/Canada/Tanzania scopes, and CAD/TZS
home-currency maintenance. Its disposable project and volumes were removed
without touching the default user stack.

The real-bank checkpoint parses all 11 supplied sanitized I&M Tanzania TZS
image-PDF statements through `im_bank_tz_pdf_v1`: all reconcile exactly, with
41 transactions, five valid zero-activity statements, and zero additions when
the largest 17-row statement is repeated. Its local OCR values are independently
checked against running balances, printed totals, and closing balances. ADR-0006
defers a named USD institution adapter; generic USD behavior remains covered by
the deterministic synthetic suite. No Phase 2 retrospective or closure section
should be written until review is approved.
