# ADR-0005: Three-Layer Money and Materialized Insights

**Date:** 2026-07-24
**Status:** Accepted
**Jira:** N/A

> Partial supersession note:
> [ADR-0008](0008-configurable-cad-tzs-home-currency.md) supersedes only this
> ADR's fixed-CAD clause and the related public-switching semantics inherited
> from ADR-0004. The original, posted, and reporting money layers; deferred
> valuation; deterministic materialization; and durable review-state decisions
> remain accepted. The decision below is preserved as the historical Stage 1
> record.

## Context

Phase 1 stores the bank-posted amount and a derived reporting amount, while
Amex foreign-spend evidence remains nested in format-specific enrichment. That
shape cannot faithfully represent a purchase made in one currency, posted to
an account in another currency, and reported across the ledger in CAD. It also
makes a missing reporting rate capable of blocking otherwise valid native
ledger data.

Phase 2 adds trends, recurring-series detection, and explainable findings.
Computing those products ad hoc on every read would make results slower, harder
to reproduce, and unable to retain a user's review decisions. Allowing a model
to infer findings or perform arithmetic would violate Ledger's deterministic
money boundary.

## Decision

Ledger will represent three independent monetary layers for a transaction:

1. Optional immutable **original** amount and currency reported for the
   merchant purchase.
2. Required immutable **posted/native** amount and currency that affected the
   selected account and is used for reconciliation.
3. Nullable derived **reporting** amount in CAD, together with the reference
   rate and rate date used to calculate it.

`original_amount` and `original_currency` must be present together and use the
same transaction-flow sign as `amount_native`. `fx_fee_amount_native` records
an explicit inline fee already included in the posted amount, while `is_fx_fee`
identifies a separately posted fee transaction. Neither form may be added to a
balance twice. Existing valid Amex foreign-spend enrichment will be backfilled
into the original-money columns without changing posted identity or creating
duplicate transactions.

Every account and statement has one posted currency. A bank relationship with
separate TZS and USD balances is represented by separate accounts, and an
import containing mixed posted currencies is rejected. Reconciliation remains:

`opening_balance + sum(amount_native) = closing_balance`

CAD is the fixed public reporting currency for Phase 2. Public requests to
switch to another base return `409 base_currency_fixed`; the internal rebuild
mechanism remains available for migration and recovery. If a booked-date or
nearest-prior rate within the configured seven-day limit is unavailable, Ledger
persists and reconciles the native transaction, leaves reporting fields null,
marks the valuation `pending_fx`, and queues retryable FX enrichment. It never
falls forward or fabricates a rate.

This supersedes ADR-0004 only where that decision made the public reporting
currency switchable. ADR-0004's native-balance, liability, utilization, and net
worth semantics remain in force.

Phase 2 analytics are deterministic and materialized in PostgreSQL. Monthly
aggregates, recurring series and occurrences, analytics settings, run metadata,
and findings are published atomically by deduplicated incremental or full
`analytics_refresh` work. Findings have stable detector fingerprints, evidence,
severity, and durable `new`, `confirmed`, `dismissed`, or `resolved` status so
recomputation preserves review state and suppression until materially new
evidence appears. No LLM computes a metric or finding.

## Alternatives Considered

- Convert every imported amount directly to CAD and discard source currency
  layers.
- Treat the merchant currency as the account currency or permit one account to
  reconcile in multiple posted currencies.
- Keep the public reporting currency switchable during Phase 2.
- Reject or roll back an otherwise valid statement when a CAD rate is missing.
- Compute all analytics on demand and keep findings ephemeral.
- Use an LLM to detect or summarize financial anomalies from transaction data.

## Consequences

- Transaction, adapter, worker, API, and UI contracts must distinguish
  original, posted, and reporting amounts and support pending CAD valuation.
- Exact native reconciliation remains available even when consolidated CAD
  analytics are partial.
- FX analytics must separate actual statement-provided fees from signed
  estimated markup and exclude known inline fees from the conversion basis.
- Materialized analytics require schema, refresh orchestration, atomic
  publication, rebuild controls, run observability, and hand-calculated tests.
- Dismissed or corrected findings remain auditable instead of being deleted.
- Sanitized institution-specific TZS and USD statements, each with exact
  reconciliation and idempotent repeat import, are mandatory Phase 2 release
  evidence and are not yet available. ADR-0006 later supersedes this consequence
  by accepting the supplied I&M Tanzania TZS set and deferring named USD
  statement support.
