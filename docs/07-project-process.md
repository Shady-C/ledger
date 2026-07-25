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

## Phase 2 Retrospective — Three-Layer Money and Deep Insights

**Completed:** 2026-07-25

The completed backlog, exact behavioral criteria, and closure evidence live in
[PHASE-2-BUILD-PLAN.md](PHASE-2-BUILD-PLAN.md). Phase 2 was approved after the
ADR-0007 market-scoped UX remediation passed its expanded gates. ADR-0008's
home-currency work remained a separate Phase 2.1 approval and was approved
independently on 2026-07-25.

### Delivered

- Explicit original, posted/native, and nullable reporting money with deferred
  FX valuation, exact reconciliation, and single-currency accounts/statements.
- Deterministic market-scoped monthly analytics, seasonality, recurring series,
  explainable findings, durable review state, and atomic publication.
- All/Canada/Tanzania scope identity, progressive conversion evidence, focused
  Home and Activity experiences, Insights FX, Settings Advanced, and `/more`.
- Deterministic CSV/XLSX ingestion and the accepted `im_bank_tz_pdf_v1` adapter
  for all 11 supplied sanitized I&M Tanzania TZS image-PDF statements.
- Separately approved Phase 2.1 CAD/TZS home reporting rebuilt from immutable
  native money, with frozen materiality profiles, switch auditing, maintenance
  state, and currency-fenced analytics generations.

### What Went Well

- The three monetary layers made native ledger acceptance independent from
  reporting-rate availability while preserving exact posted truth.
- Atomic, generation-bound analytics made deep Insights reproducible and kept
  recurring corrections and finding review state durable.
- Review feedback became explicit ADR-0007 scope and information-hierarchy
  requirements with regression coverage rather than an untracked UI patch.
- Real-bank acceptance combined bounded local OCR with balance deltas, printed
  totals, closing balances, and repeat-ingestion checks.
- Phase 2.1 stayed a separately approved gate, making its reporting-currency
  risks and rollback constraints visible.

### What Could Improve

- Market scope and information hierarchy should have been defined before the
  first Phase 2 review instead of added as remediation.
- The original fixed-CAD choice reduced initial complexity but required a
  follow-up phase and a partial supersession ADR once stable TZS reporting was
  required.
- The Phase 2 plan accumulated implementation checkpoints and approval notes;
  future phases should keep one concise current-state section and preserve
  detailed results in closure evidence.
- A named USD institution adapter still depends on receiving a sanitized real
  sample; generic USD behavior is covered but does not prove one bank layout.

### Decisions and Carry-Forward

- ADR-0005 through ADR-0008 remain the Phase 2/2.1 decisions. ADR-0008
  supersedes only the fixed-CAD/public-switching clauses identified in the
  earlier ADRs.
- The `2855.59` reconciliation, zero-row repeat ingestion, native-truth
  immutability, pending-FX behavior, All/CA/TZ isolation, CAD/TZS rebuild fence,
  analytics generation identity, and review-state durability remain permanent
  regression gates.
- ADR-0006 continues to defer a named USD statement adapter until a sanitized
  sample is supplied and explicitly scheduled.
- Forecasting, irregular-PDF AI extraction, authentication, multi-tenancy,
  investments, and budgets remain deferred.

### Closure Evidence — 2026-07-25

The permanent Phase 0–2.1 regression gates were rerun before approval and the
recorded Phase 2 review evidence was accepted. The final recorded automated
checkpoint passed `make check` with zero Svelte errors or warnings plus Ruff
and strict mypy, `make test` with 23 shared-contract, 63 web-server, 7
component, 20 Playwright, and 196 worker tests plus 1 intentional worker skip,
and the production web build.

Disposable PostgreSQL acceptance applied migrations `001`–`015`, preserved
native truth and review state across the Phase 1 upgrade, proved market scope,
CAD→TZS→CAD switching, immutable switch auditing, currency-fenced publication,
rollback/reapplication, and refusal to roll back while TZS was active. The
100,000-transaction rebuild completed in `16.385s` against `120s`; the slowest
warm materialized read was `1.721ms` against `1000ms`.

A uniquely named clean Compose stack preserved the `2855.59` closing balance
and zero-row repeat import while covering All/Canada/Tanzania scopes, both
three-layer currency directions, CAD/TZS maintenance, FX evidence, analytics,
and durable finding review. All 11 supplied I&M Tanzania TZS statements
reconciled exactly, covering 41 transactions and five zero-activity statements;
the largest 17-row statement added zero rows on repeat. Disposable resources
were removed without touching the default user stack.

## Phase 3 Process — Grounded Ask

Phase 3 is `in_progress`. Its active sequenced backlog, contracts, privacy
boundary, performance targets, and release gates live in
[PHASE-3-BUILD-PLAN.md](PHASE-3-BUILD-PLAN.md). ADR-0009 replaces the earlier
iterative-agent sketch with one bounded planning call, a closed deterministic
executor, and at most one opaque-reference narration call. ADR-0010 makes
mutable-source freshness fail closed, keeps database-derived clarification
choices local, and adds code-owned prohibited-intent enforcement.

Phase 3 cannot move to `in_review` until the permanent earlier-phase gates,
strict Ask contract/database/privacy suites, component and browser coverage,
100,000-transaction Ask benchmark, disposable stub-provider smoke, and the
one-time opt-in live Anthropic acceptance run all pass. Jira and Confluence are
not configured, so the local plan remains the backlog and `docs/` remains the
only source of truth.
