# Ledger Documentation

The files in this directory are the source of truth for Ledger. Confluence, if
configured later, is a publish target only.

Phase 1 is currently `in_review`. The integrated `make test`, `make check`,
production build, clean migration/seed, and disposable fresh-stack `make smoke`
gates are recorded as passing in the project context and changelog.

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — current phase, scope, stack, and
  working agreements
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design and longer-term roadmap
- [BUILD-PLAN.md](BUILD-PLAN.md) — executable Phase 0 plan and acceptance gates
- [PHASE-1-BUILD-PLAN.md](PHASE-1-BUILD-PLAN.md) — active Phase 1 backlog and
  acceptance gates
- [CODEBASE_HANDOFF.md](CODEBASE_HANDOFF.md) — practical developer map,
  runtime flows, invariants, extension paths, and debugging guide
- [07-project-process.md](07-project-process.md) — phase retrospectives and
  delivery process
- [decisions/](decisions/) — architecture decision records

Current decisions:

- [ADR-0001](decisions/0001-application-layer-statement-encryption.md) —
  application-layer encryption for raw statements
- [ADR-0002](decisions/0002-accept-equivalent-amex-description-columns.md) —
  equivalent Amex description-column handling
- [ADR-0003](decisions/0003-ai-categorization-proposals.md) — minimized,
  validated, and reviewable AI categorization
- [ADR-0004](decisions/0004-account-positions-and-net-worth.md) — account
  positions, card limits, base valuation, and net worth

All checked-in financial fixtures are synthetic. Sanitized institution-specific
TZS/USD exports are still user-supplied acceptance inputs, not repository
fixtures; see [CODEBASE_HANDOFF.md](CODEBASE_HANDOFF.md#fixture-status).
