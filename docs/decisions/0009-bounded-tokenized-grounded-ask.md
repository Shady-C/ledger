# ADR-0009: Bounded, Tokenized Grounded Ask

**Date:** 2026-07-25
**Status:** Accepted
**Jira:** N/A

## Context

Ledger's architecture has always required natural-language answers to be
computed from the canonical ledger rather than invented by a model. The
earlier Phase 3 sketch described an iterative tool-using agent with schema
description and result-set tools. That design left the number of model/tool
round trips open-ended and would have made database-derived values, dates, and
entity labels available to a narration model.

Phase 3 needs a smaller, auditable boundary that preserves deterministic money,
fails closed on unsupported questions, and does not create a second analytics
engine or a persistent chat-data store.

## Decision

Ledger will implement Ask as one bounded synchronous SvelteKit workflow with a
versioned `AskPlanV1` contract. A capable planning model may return exactly one
of:

- `execute`, containing one to three closed-catalog query specifications;
- `clarify`, containing one focused question and optional choices; or
- `unsupported`, containing a stable reason code and capability guidance.

The planner receives only the question, current date and validated timezone,
active market and home currency, a static DSL catalog, and at most three prior
question/validated-plan pairs. It never receives database schemas, SQL,
database rows, analytics results, entity catalogs, or finding evidence.

Code validates the complete plan before it has any effect. It resolves symbolic
dates and exact entity matches locally, rejects unsupported filter/grouping
intersections, and compiles only code-owned enum branches into parameterized
SQL. All plan inputs remain bound parameters. The executor runs the plan in one
repeatable-read, read-only transaction pinned to one published analytics
generation and home currency. It returns at most 20 table rows, at most 120
monthly points, and explicit coverage, truncation, watermark, and freshness
metadata. Exact PostgreSQL numeric results cross the API as decimal strings;
JavaScript and models do not perform financial arithmetic.

The worker records the FX-rate watermark visible inside each analytics
snapshot in the existing run-result JSON. Ask binds that exact cutoff, retains
PostgreSQL microsecond precision for source/rate watermarks, and refuses FX
reads when mutable rate data is newer than the published generation.

After successful execution, one optional cheap-model call may narrate the
answer. Every database-derived value, date, label, identifier, relationship,
and factual clause is converted first into a request-local opaque reference.
The narrator receives only those references and must return a structured
segment tree made from connective text and known fact references. Unknown
references, numeric literals, currency or percentage syntax, malformed output,
refusal, or timeout causes deterministic local narration to replace model
prose without discarding the evidence. Raw transaction descriptions, entity
lists, analytics histories, and finding evidence never enter the narrator
payload.

This decision supersedes the iterative tool-using-agent, `describe_schema`,
raw-result narration, and prompt/result-caching language in the earlier
architecture sketch. ADR-0003 remains unchanged for worker-side column mapping
and categorization. Phase 3 expands the external-AI boundary only to the
minimized planner inputs and opaque narrator references defined here.

Ask stores no server-side question, plan, answer, evidence, or conversation
history. The browser tab may retain at most three prior questions and validated
plans in memory and clears them on reload, reset, market change, or home-currency
change. Operational logs contain only a request identifier, disposition, model
tier, durations, query count, and error code. Ask responses use
`Cache-Control: no-store` and remain outside service-worker caches.

Ask is independently disabled by default. `ASK_ENABLED` gates the feature and
`ASK_PROVIDER_MODE=live|stub` defaults to the Anthropic adapter or selects a
deterministic fixture while reusing the existing Anthropic key and
capable/cheap model settings. `ASK_PROVIDER_TIMEOUT_MS=20000` bounds provider
calls. One request has a 45-second budget, each provider call has a
20-second limit, model calls are not retried automatically, and each web
process accepts at most two concurrent Ask requests.

## Alternatives Considered

- Allow a model to emit SQL after schema inspection.
- Retain the earlier open-ended tool-using agent loop.
- Send raw deterministic result rows to the narration model.
- Let the planner switch reporting currency or calculate missing values.
- Persist conversation history, evidence, or prompt/result caches.
- Generate narration only in local deterministic code.

## Consequences

- Shared contracts, provider adapters, validation, entity resolution, query
  compilation, evidence tokenization, narration validation, and UI rendering
  must evolve together and fail closed.
- Ask can answer only the cataloged aggregate, seasonality, recurring, finding,
  FX, and transaction-evidence questions; forecasting, balances/net worth,
  advice, budgets, investments, writes, and unsupported cross-dimension queries
  are rejected or clarified.
- Answers remain reproducible and auditable against one analytics generation,
  with the normalized plan and deterministic evidence shown beside prose.
- Narration may be less fluent when the provider fails validation, but the
  financial evidence remains available and trustworthy.
- No database migration is required because plans and conversations are not
  persisted.
