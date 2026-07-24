# Ledger — Phase 1 Build Plan

Current Phase: 1
Phase Status: in_review
Jira Epic: N/A

## Outcome

Phase 1 turns the Phase 0 vertical slice into a multi-account,
multi-institution, multi-currency ledger. It adds governed AI enrichment while
keeping all balances, conversions, reconciliation, and analytics deterministic.

## Sequenced Backlog

1. Close Phase 0 and record ADR-0003 and ADR-0004.
2. Add settings, credit-limit, category-provenance, proposal, mapping, and job
   schema migrations with backward-safe defaults.
3. Add institution/account/category mutation APIs and shared contracts.
4. Generalize jobs and implement automatic categorization backfill plus user
   override precedence.
5. Add Frankfurter-backed historical FX caching and atomic base-currency
   rebuilds for CAD, USD, and TZS.
6. Add OFX/QFX ingestion and AI-assisted mapping for unknown CSV/XLSX formats.
7. Add corrected account positions, credit utilization, net worth, and FX-fee
   analytics.
8. Split the SvelteKit UI into Dashboard, Transactions, Accounts, Categories,
   and Imports routes under a shared responsive shell.
9. Add contract, worker, integration, component, and browser regression tests.
10. Extend the fresh-stack smoke test, update the handoff documentation, and
    move Phase 1 to review.

## Acceptance Gates

- Phase 0 closing balance remains `2855.59`; repeat ingestion adds zero rows.
- OFX1/OFX2 bank and credit-card fixtures normalize and reconcile, while
  investment statements fail closed.
- Sanitized USD and TZS statement samples ingest with dated, cached FX rates.
- Known merchants make no model call; unknown merchants use minimized structured
  proposals and never overwrite transaction-specific user choices.
- Base-currency rebuilds are all-or-nothing and preserve every native value.
- Net worth reports correct asset/liability polarity and explicit exclusions.
- Missing card limits never produce a fabricated utilization value.
- All five routes work on desktop and mobile with URL-stable transaction
  filters and accessible write workflows.
- `make test`, `make check`, and the fresh-stack Phase 1 smoke test pass.

## Deferred

- Irregular-PDF AI extraction and local OCR/model fallback
- Authentication and multi-tenant isolation
- Live bank connections
- Investment, loan, property, and other manual balance-sheet accounts
- Vector-similarity categorization
- Trends, anomalies, recurring detection, forecasting, and natural-language
  queries
