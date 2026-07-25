# ADR-0007: Market Scopes and Progressive Disclosure

**Date:** 2026-07-24
**Status:** Accepted
**Jira:** N/A

## Context

Phase 2 faithfully exposes original, account-posted, and CAD-reporting money,
but showing every layer and both running balances in the transaction list makes
audit evidence dominate everyday use. Canada- and Tanzania-focused views also
cannot be derived safely from currency: either market can contain foreign
purchases or accounts posted in USD.

## Decision

Ledger remains one product, repository, canonical ledger, ingestion pipeline,
and deterministic analytics engine. Accounts gain an explicit nullable market
membership, limited initially to Canada (`CA`) and Tanzania (`TZ`). Existing
accounts are not inferred or backfilled; unassigned accounts remain visible in
the All scope until the user classifies them. New accounts require a market.

A separate nullable `market_profile` setting controls first-visit and
new-account defaults. It never changes the ledger's reporting currency. The
selected presentation scope is `All`, `CA`, or `TZ`, is represented in URLs,
and filters account-backed reads before aggregation. During Phase 2 all scoped
consolidated values remain CAD.

Materialized analytics carry their market scope. The worker publishes the All
view plus CA and TZ views from the corresponding account transactions, and
scope participates in detector fingerprints and review state. Reassigning a
funded account queues a full analytics refresh without changing any source
transaction or reconciliation value.

Transaction lists show one account-posted amount and compact conversion-state
indicators. Original money, reporting valuation, rates, fees, estimated markup,
and both running balances move into an on-demand transaction detail drawer.
Dashboard, navigation, Insights, and settings use the same progressive-
disclosure boundary.

## Alternatives Considered

- Maintain separate Canadian and Tanzanian products or codebases.
- Infer market from posted or reporting currency.
- Attach market only to institutions, despite multinational institutions and
  accounts without an institution.
- Keep every monetary layer visible in every transaction row.
- Make market scope switch the reporting currency.

## Consequences

- Account, settings, query, API, analytics, and UI contracts gain explicit
  market semantics independent of currency.
- Existing accounts require a non-blocking one-time classification workflow.
- Market-scoped analytics increase materialized rows and must remain within the
  existing performance gate.
- Categories and institutions stay ledger-wide; imported statements inherit
  market through their selected account.
- Home-currency changes remain outside this decision and are governed separately
  by ADR-0008.
