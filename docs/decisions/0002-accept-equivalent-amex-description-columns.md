# ADR-0002: Accept Equivalent Amex Description Columns

**Date:** 2026-07-24
**Status:** Accepted
**Jira:** N/A

## Context

Some American Express XLSX exports contain both `Description` and `Merchant`
columns. The observed export populates both columns for every transaction with
the same text. Ledger previously treated both headers as aliases for the
canonical description and rejected the statement as ambiguous even though the
source values did not conflict.

## Decision

The Amex adapter accepts multiple recognized description aliases only when
their whitespace-normalized, case-insensitive values agree on every
transaction row. It chooses columns using the adapter's explicit alias
preference order, with `Description` ahead of `Merchant` and `Details`.

Multiple date, amount, and other aliases remain ambiguous. Description aliases
with different values also fail closed. Worker failure logs include exception
tracebacks while persisted and API-facing failure reasons remain sanitized.

## Alternatives Considered

- Always prefer `Description`: simpler, but could silently discard conflicting
  merchant data from an unfamiliar export.
- Remove `Merchant` as a recognized alias: fixes this export when Description
  exists, but breaks exports where Merchant is the only descriptive field.
- Continue rejecting all duplicate aliases: safest structurally, but rejects a
  valid, deterministic Amex export whose duplicate values can be verified.

## Consequences

- Current Amex exports with equivalent `Description` and `Merchant` columns
  ingest without manual workbook edits.
- Conflicting aliases remain visible failures instead of silently selecting a
  source value.
- Regression tests must cover equivalent and conflicting duplicate columns.
- Operational logs contain actionable tracebacks; public job responses do not
  expose exception details.
