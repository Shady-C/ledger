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

## Phase 1 Process

The active backlog and acceptance gates live in
[PHASE-1-BUILD-PLAN.md](PHASE-1-BUILD-PLAN.md). Documentation and ADRs are
updated before behavior changes; implementation is complete only after the
fresh-stack smoke path and handoff documentation agree with the code.

### Review Gate — 2026-07-24

The integrated test, static-check, production-build, clean-migration, and
disposable fresh-stack smoke gates passed. Phase 1 advanced to `in_review`.
Institution-specific TZS/USD exports remain an optional review input when the
user supplies sanitized samples; all checked-in protocol/failure fixtures are
synthetic.
