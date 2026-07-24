# ADR-0003: Privacy-Minimized AI Categorization Proposals

**Date:** 2026-07-24
**Status:** Accepted
**Jira:** N/A

## Context

Phase 0 assigns categories with deterministic rules and sends unknown merchants
to `Other`. Phase 1 needs to improve those assignments without making ledger
ingestion depend on an external model or sending the complete transaction
history to a provider. The existing repository also creates missing category
names during persistence, which would allow an unchecked model response to
silently mutate the taxonomy.

## Decision

Ledger will scan transactions locally and send only distinct unresolved
merchant-and-flow contexts to the configured LLM. A request contains an opaque
key, normalized merchant text, a coarse flow type, and an allowlist of category
IDs. It contains no amount, date, balance, account identifier, transaction ID,
or statement content.

The model returns structured proposals. Existing-category proposals at or
above the configured confidence threshold may be applied automatically after
schema and business validation. Lower-confidence results and every proposed
new category require review. New categories are created only by an explicit
user acceptance action.

Categorization runs as a separate idempotent job after financial persistence.
Transaction-specific user overrides win over explicit user merchant mappings;
those win over account-aware deterministic rules, which win over learned AI
mappings and the protected fallback. Provider failures leave the ledger and
reconciliation result untouched. Exact learned mappings are Phase 1; the
dormant vector-similarity path remains deferred.

## Alternatives Considered

- Send every transaction, including financial context, to the LLM.
- Restrict the model to existing categories and never propose taxonomy changes.
- Require manual approval for every valid model assignment.
- Run categorization inside the ingestion transaction.

## Consequences

- Model usage and disclosure shrink as the mapping table learns.
- The job and API contracts need categorization-specific results and review
  states.
- Transactions need category provenance, confidence, and override precedence.
- Model output must use validated category IDs; the worker may no longer create
  categories from arbitrary names.
- The Categories page becomes the review surface for low-confidence and new
  category proposals.
