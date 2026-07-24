# ADR-0006: I&M Tanzania PDF Acceptance and Deferred USD Statements

**Date:** 2026-07-24
**Status:** Accepted
**Jira:** N/A

## Context

Phase 2 originally required one real sanitized TZS statement and one real
sanitized USD statement as institution-specific release evidence. Eleven
sanitized I&M Bank Tanzania TZS statement PDFs are now available locally. They
share a stable statement layout but contain page images rather than an
extractable PDF text layer. No real USD institution statement has been supplied,
and the user has explicitly deferred USD-statement acceptance for now.

The existing generic PDF adapter is intentionally limited to extractable tables.
Sending financial PDFs to a vision model would violate the Phase 2 privacy and
deterministic-arithmetic boundary, while accepting unverified OCR values would
weaken exact reconciliation.

## Decision

Ledger adds the versioned `im_bank_tz_pdf_v1` adapter for the supplied I&M Bank
Tanzania TZS statement layout. The adapter uses a local Tesseract executable and
never sends PDF content to an external service or model. It accepts only the
known header fingerprint, TZS asset accounts, bounded page and rendered-pixel
counts, and bounded OCR execution time.

OCR is treated as evidence, not ledger truth. For every transaction, the
adapter derives the signed posted amount from consecutive running balances and
requires that magnitude to equal the OCR amount column. It then verifies the
printed debit/credit totals, final running balance, and statement closing
balance before returning rows. A zero-activity statement is valid only when its
opening and closing balances agree. Any ambiguous or inconsistent evidence
fails closed without persisting financial rows.

The supplied PDFs remain local, ignored acceptance inputs. Small sanitized
OCR-text derivatives representing one transactional page and one zero-activity
page are checked in for deterministic unit tests. Docker installs Tesseract so
the application path is self-contained; direct host execution of the adapter or
acceptance script requires a local Tesseract installation.

Real institution-specific USD statement acceptance is deferred until a
sanitized sample is supplied and explicitly brought into scope. Phase 2 keeps
its generic USD CSV/XLSX/OFX contracts and synthetic three-layer USD tests, but
the absence of a named USD adapter is no longer a Phase 2 review or completion
blocker. This decision supersedes only the dual real-TZS/real-USD release-
evidence requirement in ADR-0005; all three-layer and single-currency-account
rules remain unchanged.

## Alternatives Considered

- Send the image PDFs to a general vision or document-AI service.
- Treat OCR output as trusted values without balance and totals validation.
- Require the bank to provide CSV/XLSX exports before accepting TZS statements.
- Keep Phase 2 blocked until a real USD statement becomes available.
- Commit the complete sanitized PDFs as automated fixtures.

## Consequences

- The worker image has a Tesseract runtime dependency, and local direct runs
  need the same executable.
- The adapter is deliberately institution/layout specific. A material export
  change requires a new fingerprint, sanitized evidence, and adapter version.
- Exact reconciliation, repeat-ingestion, zero-activity, corruption, and
  end-to-end object-store/worker/database behavior are testable without an AI
  provider.
- Private acceptance PDFs remain outside version control; automated CI uses
  sanitized text derivatives, while the local acceptance command validates all
  supplied PDFs when present.
- Phase 2 may advance to review on the accepted TZS evidence and all other
  gates. A future named USD adapter remains separate follow-up work.
