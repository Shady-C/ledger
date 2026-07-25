# Ledger Documentation

The files in this directory are the source of truth for Ledger. Confluence, if
configured later, is a publish target only.

Phase 1 completed on 2026-07-24. Phase 2 is `in_review`; its three-layer money,
explicit Canada/Tanzania scopes, deterministic analytics, progressive
transaction disclosure, Insights, performance, and real-bank gates have
passed. The working tree also contains ADR-0008's separately gated Phase 2.1
implementation for stable CAD/TZS home reporting; its approval remains separate
from Phase 2. A named USD institution adapter is deferred by ADR-0006.

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
  three-layer money, Stage 1 fixed-CAD reporting, deferred valuation, and
  materialized reviewed insights; ADR-0008 supersedes only the fixed-CAD clause
- [ADR-0006](decisions/0006-im-bank-tanzania-pdf-and-deferred-usd-acceptance.md)
  — deterministic local-OCR I&M Tanzania TZS acceptance and deferred named USD
  statement support
- [ADR-0007](decisions/0007-market-scopes-and-progressive-disclosure.md) —
  account-level Canada/Tanzania scopes, separate market profile, and
  progressive monetary disclosure
- [ADR-0008](decisions/0008-configurable-cad-tzs-home-currency.md) — safe,
  currency-fenced CAD/TZS home reporting and frozen materiality profiles

Complete statement PDFs remain ignored local acceptance inputs. Two checked-in
sanitized OCR-text derivatives cover the I&M Tanzania parser without retaining
full statements. All 11 supplied TZS PDFs reconcile exactly, and the largest
17-row statement adds zero rows on repeat. See
[PHASE-2-BUILD-PLAN.md](PHASE-2-BUILD-PLAN.md#review-state).
