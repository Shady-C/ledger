# ADR-0010: Fail-Closed Ask Freshness and Local Clarification

**Date:** 2026-07-25
**Status:** Accepted
**Jira:** N/A

## Context

ADR-0009 pins Ask to one published analytics generation, but the first
implementation allowed an answer after newer ledger-source changes by filtering
transactions at the generation watermark and showing a warning. Ledger source
and entity tables are mutable rather than versioned. Updating a transaction can
therefore remove its current row from a watermark-filtered query, while an
account market change or category/merchant rename can alter live joins. A
warning cannot make those reads reconstruct the generation-era state.

Local entity resolution also returned database-derived labels and qualifiers as
clarification buttons. Appending a selected label to the next natural-language
question would send it to the external planner, contrary to ADR-0009's rule that
the planner receives no entity catalog or masked account reference.

Finally, unsupported write, SQL, forecast, advice, balance, and net-worth
requests depended on the provider returning an unsupported plan. Structural
plan validation alone cannot enforce those semantic boundaries if a provider
returns an otherwise valid execute plan.

## Decision

Ask fails closed with `analytics_rebuilding` whenever a transaction, statement,
account, category, or merchant is newer than the published source watermark.
Freshness is checked before planning and again inside the execution snapshot.
The worker computes future source watermarks from the same five tables. FX reads
continue to reject generations older than mutable FX reference data.

Database-derived clarification choices use a local opaque entity token. A
selection request carries that token, the query id, and the previously validated
execute plan in a separate strict field. The browser keeps the original question
unchanged, the capable planner is skipped, and the server recomputes and
validates the token against the current entity kind, candidate set, and market
scope inside the read-only snapshot. Optional narration still receives only
request-local opaque fact references. Provider-authored clarification choices
remain ordinary label-only choices because they contain no local catalog data.

A conservative code-owned intent gate returns a validated unsupported response
for canonical raw-SQL, write, forecast, financial-advice, balance, and net-worth
requests before any database or provider call. The closed query schema and
parameterized compiler remain the primary enforcement boundary for all other
requests.

## Alternatives Considered

- Continue filtering live rows at the old watermark and show a warning. Rejected
  because mutable rows and labels cannot be reconstructed from current tables.
- Version every ledger and entity row for generation-era reconstruction.
  Rejected for Phase 3 because it requires a substantially broader storage and
  migration design.
- Append a selected local label or masked reference to the next planner
  question. Rejected because it expands the external planner's data boundary.
- Persist server-side clarification sessions. Rejected because Phase 3 stores no
  questions, plans, selections, or conversation state; stateless token
  validation is sufficient for this local single-user application.

## Consequences

Ask can be temporarily unavailable after a source edit until a matching
analytics generation is published, even when a particular query might otherwise
be answerable. That conservative interruption preserves the generation claim.
Category and merchant timestamps now participate in analytics watermarks.

Clarification request/response contracts gain typed choice objects and an
optional local-selection field. Tokens are selectors, not authorization; the
server still validates the supplied plan, query, entity kind, candidate set,
scope, source freshness, and read-only execution boundary. Local choice labels
remain visible to the user but never enter a provider payload.

The local intent gate deliberately covers only clear prohibited forms so normal
historical searches are not reclassified by incidental words in transaction
descriptions. Live-provider adversarial acceptance remains required.
