# ADR-0008: Configurable CAD or TZS Home Currency

**Date:** 2026-07-24
**Status:** Accepted
**Jira:** N/A

## Context

ADR-0005 fixed CAD as the Phase 2 reporting lens so three-layer money and
materialized analytics could ship without concurrent-currency publication
risks. A genuine Tanzania reporting profile now requires TZS-valued
transactions and analytics rather than a visual theme. The existing recovery
rebuild can reuse a prior base value when a target rate is missing, so removing
the CAD guard alone could relabel stale CAD as TZS.

## Decision

Ledger will support exactly CAD and TZS as stable home/reporting currencies.
This supersedes only ADR-0005's fixed-CAD clause and ADR-0004's semantics for a
public reporting-currency switch. All other money-layer, account-position, and
net-worth decisions in those ADRs remain in force.
Market profile, active market scope, account-posted currency, and home currency
remain independent. Existing wire names such as `baseCurrency`, `amountBase`,
and `currencyBase` remain for compatibility; product copy calls this the home
currency or reporting value.

A home-currency change is an explicit Advanced maintenance action. Under the
existing base-currency advisory lock, Ledger recomputes every reporting value
from immutable account-posted money: identity rows use rate `1`, rows with a
valid target rate are recalculated, and rows without one become `pending_fx`.
No previous reporting amount or rate is reused. Transaction values and ledger
settings change atomically, incompatible analytics are unpublished, target FX
recovery and a full analytics rebuild are queued, and Insights remains in a
clear rebuilding state until a generation tagged with the active currency is
published. A failed analytics run never rolls reporting values back; Advanced
settings exposes status and retry. Ingestion and native reconciliation remain
available. Each successful currency change also appends an immutable audit row
containing the exact conversion rate, source, source date, target policy, and
switch timestamp used for recurring override conversion.

Analytics runs, aggregates, evidence, and relevant fingerprints carry their
home currency and threshold-policy version. Publication rejects a generation
whose currency differs from the active setting. CAD retains the accepted low,
balanced, and high materiality floors of 25, 10, and 5 plus the price-increase
floor of 1. On the first TZS switch, deterministic code converts those values
once using an accepted dated CAD-to-TZS rate under the seven-day staleness rule,
rounds them to Ledger's two-decimal reporting precision, and persists the exact
frozen TZS profile, source rate/date, and policy version.

Native review evidence remains valid. Currency-valued findings resolve and are
regenerated in the target currency. Recurring status and cadence survive;
user-entered base-currency amount overrides are converted with recorded switch
evidence rather than relabelled. Base-comparison recurring fingerprints are
transformed in place for the target currency and policy so their durable row,
review status, cadence, and linked overdue review state survive without
presenting old reporting evidence as current. Original- and native-comparison
recurring identities remain stable.

## Alternatives Considered

- Keep CAD permanently fixed.
- Treat market scope as a reporting-currency toggle.
- Support every ISO currency accepted by the FX provider.
- Reuse existing reporting fields when target rates are unavailable.
- Keep serving an older currency's Insights during a switch.
- Recalculate materiality thresholds continuously with live FX rates.

## Consequences

- CAD-only database, worker, API, shared-contract, and UI assumptions must be
  generalized and regression-tested for CAD and TZS.
- Analytics publication requires a currency fence and a visible maintenance
  state when no compatible generation exists.
- Threshold policies become durable, versioned financial configuration.
- Migration rollback must refuse while a non-CAD lens is active instead of
  silently coercing data.
- Native amounts, statement reconciliation, deduplication, and account currency
  constraints remain unchanged.
