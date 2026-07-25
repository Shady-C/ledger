# ADR-0004: Account Positions, Credit Limits, and Net Worth

**Date:** 2026-07-24
**Status:** Accepted
**Jira:** N/A

> Historical supersession note:
> [ADR-0005](0005-three-layer-money-and-materialized-insights.md) first
> superseded this ADR's public base-currency switchability by fixing CAD for the
> Phase 2 reporting lens. [ADR-0008](0008-configurable-cad-tzs-home-currency.md)
> later supersedes only those public-switching semantics with a confirmed,
> maintenance-gated CAD/TZS home-currency change. Native-balance, liability,
> utilization, and net-worth semantics remain accepted.

## Context

Phase 0 displays every account with the same treatment and its consolidated
balance query adds credit-card debt to asset balances. It has no account
management workflow, credit-limit metadata, switchable persisted base
currency, or trustworthy multi-currency net-worth calculation. The roadmap
previously deferred multi-account consolidation to Phase 2.

## Decision

Phase 1 will keep one account table and classify existing account kinds as
asset accounts (`chequing`, `savings`, `wallet`) or credit-card liabilities. A
credit card may store an optional positive credit limit in its native currency.
Limits and available credit never contribute to net worth.

Current native balance remains the account truth. For a valuation, Ledger
converts the current native balance using a cached rate no later than the
valuation date. Asset-account contribution equals the converted balance;
credit-card contribution is its negation. Positive contributions are assets and
negative contributions are liabilities, which also handles overdrafts and card
overpayments. Accounts without a verified balance or usable rate are excluded
and reported, making the result explicitly partial.

A non-null source-reported balance is an eligible anchor when reconciliation is
`ok` or `gap`. A one-sided statement may remain `pending` when the format (for
example OFX with only `LEDGERBAL`) provides no opening amount; its reported
balance is still eligible. A `mismatch` balance is never an anchor.

The ledger-wide base currency is stored in PostgreSQL, initially CAD. Switching
it is an atomic background rebuild of derived base values; immutable native
amounts never change. Account kind and native currency become immutable after
ledger data exists.

## Alternatives Considered

- Use separate bank-account and credit-card tables.
- Treat credit limits or available credit as assets.
- Sum native balances without conversion.
- Include transaction net activity as an estimated current balance.
- Keep net worth in Phase 2.

## Consequences

- Net worth and credit utilization are deterministic API calculations, not UI
  arithmetic.
- FX availability and balance completeness become visible product states.
- Account summaries need native and base valuation metadata.
- Base-currency rebuilds and ingestion must be serialized to avoid mixed-base
  reads.
- Phase 1 scope expands to account management and multi-account consolidation.
