# ADR-0011: Wealthsimple Chequing PDF v1

**Date:** 2026-07-26
**Status:** Accepted
**Jira:** N/A

## Context

Before this adapter, six retained Wealthsimple chequing statement PDFs reached
the generic extractable-PDF path, but their positioned text was not a
conventional table. The generic parser therefore returned the terminal
`needs_ai` disposition without writing statement or transaction rows. Read-only
local analysis showed that this one stable layout contains 76 transaction rows
across the six files and that its printed running balances and statement
summaries reconcile exactly.

Phase 3 otherwise focuses on bounded grounded Ask. General unknown-PDF
extraction, governed mapping/review, OCR fallback, and local-model support remain
Phase 4 work. Leaving a known, locally verifiable text-PDF layout unsupported
would nevertheless force a manual conversion even though Ledger can parse it
without widening the model or privacy boundary.

## Decision

Ledger adds the versioned `wealthsimple_chequing_pdf_v1` adapter as a targeted
Phase 3 exception. The adapter runs before the generic PDF-table fallback and
accepts only the known Wealthsimple chequing fingerprint for a CAD asset
account. It uses positioned text from `pdfplumber` locally; it performs no OCR
and sends no PDF content, text, account data, or transaction evidence to an
external provider or model.

The adapter parses the statement period, masked account reference,
opening/closing summary, repeated page headers, printed page counters, booked
and posted dates, wrapped descriptions, Unicode negative signs, signed amounts,
and running balances. The selected account kind and currency must match, and
the masked reference must be compatible with the selected account.

Parsing fails closed before persistence unless all evidence is unambiguous:

- every transaction date is within the printed statement period;
- printed page numbers are contiguous and their total equals the PDF page
  count;
- each previous balance plus the signed amount equals the next printed running
  balance using exact decimal arithmetic;
- opening balance plus the transaction sum equals the printed closing balance;
- the final running balance equals that same closing balance; and
- no transaction-like content is left unparsed.

A zero-activity statement is accepted only when opening and closing balances
are equal and no transaction-like content is present. A changed fingerprint,
duplicate or ambiguous header, missing row, malformed period, account or
currency mismatch, balance inconsistency, or summary mismatch writes no
financial rows and ends in a terminal non-success outcome. An unmatched
fingerprint continues to the generic PDF fallback and may settle as
`needs_ai`; a matched adapter that discovers invalid financial evidence fails
the ingest instead of relabeling corrupted input as merely unsupported.

The public HTTP and database contracts do not change. The existing `adapter`
job-detail field identifies successful files as
`wealthsimple_chequing_pdf_v1`. In the Imports UI, terminal `needs_ai` is
described truthfully as “Needs format support” or “Needs attention,” not as
pending AI work. Terminal `done` and `needs_ai` jobs show no retry counter, and
content-addressed PDF object names are rendered as privacy-safe labels such as
`PDF statement · …c99`. Original filenames continue to be discarded under
ADR-0001.

Private source PDFs remain ignored local inputs and are not committed. Tests
use sanitized derivatives that preserve the two-page layout and arithmetic
edge cases without retaining private account or transaction content.

## Alternatives Considered

- Leave the statements unsupported until the general Phase 4 PDF workflow.
- Loosen the generic PDF/CSV header rules enough to guess at positioned text.
- Send the PDFs to an external document-AI or vision provider.
- Add a general local OCR/model fallback during Phase 3.
- Require manual CSV conversion before import.

## Consequences

- Wealthsimple chequing text PDFs matching this exact layout can be imported
  deterministically and provider-free; materially changed layouts require a new
  fingerprint and adapter version rather than weaker validation.
- General unknown or irregular PDFs still fail closed and remain Phase 4 scope;
  this decision does not create a universal PDF parser, OCR fallback, or manual
  mapping workflow.
- Automated coverage must include a sanitized two-page success fixture,
  positive and negative amounts, Unicode minus, repeated headers, wrapped
  descriptions, zero activity, whole-page omission, fingerprint/account/
  currency rejection, and all date, row, balance, and summary failure modes.
- The 2026-07-26 post-deployment acceptance reused the six retained encrypted
  object keys while preserving the original terminal job for audit history. A
  fresh ingest added 76 rows across six reconciled statements; the identical
  repeat added zero rows and skipped all 76 existing transactions.
- No schema migration or public API version is required.
