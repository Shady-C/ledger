# Ledger Documentation

The files in this directory are the source of truth for Ledger. Confluence, if
configured later, is a publish target only.

Phase 1 completed on 2026-07-24. Phase 2 and its separately approved Phase 2.1
follow-up completed on 2026-07-25 after their permanent gates were rerun and
accepted. Phase 3 is `in_progress`: it adds a bounded, read-only, grounded Ask
workflow to Insights under ADR-0009, with fail-closed freshness and local-only
clarification refined by ADR-0010. A named USD institution adapter remains
deferred by ADR-0006.

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — current phase, scope, stack, and
  working agreements
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design and longer-term roadmap
- [BUILD-PLAN.md](BUILD-PLAN.md) — executable Phase 0 plan and acceptance gates
- [PHASE-1-BUILD-PLAN.md](PHASE-1-BUILD-PLAN.md) — completed Phase 1 backlog and
  closure record
- [PHASE-2-BUILD-PLAN.md](PHASE-2-BUILD-PLAN.md) — completed Phase 2/2.1
  backlog, acceptance gates, and closure record
- [PHASE-3-BUILD-PLAN.md](PHASE-3-BUILD-PLAN.md) — active Phase 3 backlog,
  public contracts, privacy boundary, and release gates
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
- [ADR-0009](decisions/0009-bounded-tokenized-grounded-ask.md) — bounded Ask
  planning, deterministic query execution, and opaque-reference narration
- [ADR-0010](decisions/0010-fail-closed-ask-freshness-and-local-clarification.md)
  — fail-closed mutable-source freshness, local clarification tokens, and
  code-owned prohibited-intent enforcement

Complete statement PDFs remain ignored local acceptance inputs. Two checked-in
sanitized OCR-text derivatives cover the I&M Tanzania parser without retaining
full statements. All 11 supplied TZS PDFs reconcile exactly, and the largest
17-row statement adds zero rows on repeat. See
[PHASE-2-BUILD-PLAN.md](PHASE-2-BUILD-PLAN.md#closure-state).
