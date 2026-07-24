# Ledger Documentation

The files in this directory are the source of truth for Ledger. Confluence, if
configured later, is a publish target only.

Phase 1 completed on 2026-07-24. Phase 2 is currently `in_review`; its
three-layer multi-currency, deterministic analytics, Insights, performance, and
real-bank gates are defined in the build plan. The current working tree contains
the multi-currency migrations/worker, conventional and learned CSV/XLSX
evidence mappings, analytics materialization, APIs, Insights UI, and the named
`im_bank_tz_pdf_v1` adapter. Automated test/check/build, database,
100,000-transaction performance, fresh-stack smoke, and supplied I&M Tanzania
TZS acceptance gates have passed. A named USD institution adapter is deferred
by ADR-0006; Phase 2 awaits review approval rather than more implementation.

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — current phase, scope, stack, and
  working agreements
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design and longer-term roadmap
- [BUILD-PLAN.md](BUILD-PLAN.md) — executable Phase 0 plan and acceptance gates
- [PHASE-1-BUILD-PLAN.md](PHASE-1-BUILD-PLAN.md) — completed Phase 1 backlog and
  closure record
- [PHASE-2-BUILD-PLAN.md](PHASE-2-BUILD-PLAN.md) — Phase 2 backlog, acceptance
  gates, and review state
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
- [ADR-0005](decisions/0005-three-layer-money-and-materialized-insights.md) —
  three-layer money, fixed CAD reporting, deferred valuation, and materialized
  reviewed insights
- [ADR-0006](decisions/0006-im-bank-tanzania-pdf-and-deferred-usd-acceptance.md)
  — deterministic local-OCR I&M Tanzania TZS acceptance and deferred named USD
  statement support

Complete statement PDFs remain ignored local acceptance inputs. Two checked-in
sanitized OCR-text derivatives cover the I&M Tanzania parser without retaining
full statements. All 11 supplied TZS PDFs reconcile exactly, and the largest
17-row statement adds zero rows on repeat. See
[PHASE-2-BUILD-PLAN.md](PHASE-2-BUILD-PLAN.md#review-state).
