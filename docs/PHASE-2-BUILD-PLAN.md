# Ledger — Phase 2 Build Plan

Current Phase: 2
Phase Status: in_review
Jira Epic: N/A

## Outcome

Phase 2 makes multi-currency ledger truth explicit and adds deterministic,
reviewable insights. Transactions preserve original purchase evidence, exact
account-posted values, and a nullable CAD reporting valuation. The application
then materializes trends, seasonality, recurring activity, renewals, price
changes, anomalies, duplicates, reconciliation issues, coverage gaps, and
pending-FX findings without delegating arithmetic or detection to an LLM.

## Governing Decisions

- [ADR-0005](decisions/0005-three-layer-money-and-materialized-insights.md)
  defines the three monetary layers, fixed CAD reporting, deferred valuation,
  deterministic materialization, and durable finding review state.
- [ADR-0006](decisions/0006-im-bank-tanzania-pdf-and-deferred-usd-acceptance.md)
  defines the bounded local-OCR acceptance path for the supplied I&M Tanzania
  TZS statements and defers a named USD institution adapter.
- Accounts remain single-currency. Separate TZS and USD balances at one bank
  are separate ledger accounts.
- Forecasting, natural-language querying, outbound notifications,
  authentication, multi-user tenancy, irregular-PDF AI extraction, manual
  assets/liabilities, investments, and budgets are not Phase 2 work.

## Sequenced Backlog

1. Close Phase 1, publish this build plan and ADR-0005, and move the active
   phase metadata to Phase 2.
2. Add three-layer transaction fields, fixed-CAD constraints, nullable reporting
   valuation, explicit FX-fee representation, and safe Amex enrichment
   backfill without changing posted transaction identity.
3. Update canonical worker models, known and learned CSV/XLSX mappings,
   persistence, single-currency validation, deferred valuation, and retryable
   FX behavior.
4. Extend transaction, account, dashboard, and FX contracts with exact decimal
   original/posted/reporting values, `valued | pending_fx` status, and explicit
   complete/partial coverage metadata.
5. Replace separate native/base transaction columns with one compact amount
   stack, remove the public base-currency switch control, and clearly separate
   actual FX fees from estimated markup.
6. Add PostgreSQL storage for monthly aggregates, recurring series and
   occurrences, durable findings, analytics settings, and analytics-run
   metadata.
7. Add deduplicated `analytics_refresh` work with atomic publication,
   incremental refresh after source changes, and a recoverable full rebuild.
8. Implement monthly trends, month-over-month/year-over-year comparisons,
   trailing three-month baselines, top movers, and month-of-year seasonality
   with explicit insufficient-history and partial-coverage states.
9. Implement weekly, biweekly, monthly, quarterly, and annual recurring
   detection, expected-next-date metadata, overdue state, renewal/price-change
   detection, and user corrections that survive recomputation.
10. Implement deterministic unusual-amount, unusual-frequency, monthly-spike,
    near-duplicate, recurring-price, overdue, reconciliation, coverage, and
    pending-valuation findings with stable fingerprints and durable review
    states.
11. Add the Insights summary/trends/seasonality/recurring/findings/settings and
    rebuild APIs; build `/insights` Overview, Trends, Recurring, and Findings
    tabs plus the concise Dashboard summary and unread badge.
12. Add versioned adapters only from supplied sanitized institution exports,
    complete I&M Tanzania TZS reconciliation and idempotency acceptance, run
    all regression/performance/fresh-stack gates, update the handoff, and move
    the phase to review. A named USD institution adapter is deferred by
    ADR-0006 while generic USD behavior remains covered.

## Current Implementation Checkpoint

Backlog items 1–11 have implementation in the working tree: migrations `012`
and `013`, three-layer transaction persistence and Amex backfill, fixed CAD and
deferred FX behavior, deterministic/learned tabular evidence mapping, the
materialized analytics engine, shared/API contracts, `/insights`, the amount
stack, and Dashboard integration. Conventional XLSX files have a deterministic
`generic_xlsx_v1` adapter that reuses the generic CSV table rules; this is not a
named institution adapter and does not satisfy real-bank acceptance.

Incremental `analytics_refresh` runs detect transaction months changed since
the previous published source watermark, recompute all aggregate dimensions for
those months, and copy unaffected monthly rows into the next generation.
Recurring series and findings are recomputed over the full ledger in both modes
because their evidence can cross month boundaries. Full mode recomputes all
monthly periods plus those ledger-wide detectors. Either mode publishes one
generation atomically and reports the affected-period list in its job result.

Backlog item 12 is now implemented for the supplied I&M Tanzania TZS layout.
The versioned `im_bank_tz_pdf_v1` adapter uses bounded local Tesseract OCR and
accepts a transaction only after its amount agrees with the running-balance
delta, printed totals, and statement closing balance. All 11 supplied local
PDFs reconcile exactly: 41 transactions in total, five valid zero-activity
statements, and a 17-row statement that adds zero rows on repeat. The same
17-row file passes the encrypted object-store/web/worker/PostgreSQL path. A
named USD adapter is deliberately deferred under ADR-0006 and is not a review
or completion blocker.

A disposable database checkpoint has applied migrations `001`–`013` from
empty, upgraded Phase 1 rows without changing posted or CAD amounts, backfilled
valid Amex original-money evidence, exercised the account/statement/transaction
currency constraints and pending-CAD TZS job path, and rolled back/reapplied
`012`/`013`. This satisfies a migration checkpoint only; it does not replace the
full release gates below.

The checked-in `make benchmark-analytics` disposable benchmark has also passed
with exactly 100,000 synthetic transactions: the production full refresh took
`8.298s` (limit `120s`) and the slowest warm materialized read took `2.212ms`
(limit `1000ms`) before cleaning up its temporary database. This satisfies the
stated performance threshold, not the real-bank gate.

The final automated synthetic verification checkpoint also passes `make check`
(Svelte zero errors/warnings, Ruff, strict mypy across 32 source/script files),
`make test` (22 shared, 48 web-server, 7 component, 15 Playwright, and 185
worker tests, plus 1 intentional worker skip), and `pnpm build`. The disposable
PostgreSQL checkpoint passes as described above. A final isolated Compose rerun rebuilt
the current images, applied clean migrations `001`–`013` plus seed, reconciled
the Phase 0 six-row statement to `2855.59` with zero rows on repeat, and passed
the synthetic Phase 2 USD/TZS, three-layer, fixed-CAD, FX-evidence, analytics,
and Insights-review smoke contract. The named disposable project and volumes
were removed without touching the default user stack. Together with the real
TZS acceptance evidence above, these results advance Phase 2 to `in_review`.
Closure still requires review approval; no Phase 2 retrospective is recorded
yet.

## Public Interfaces

The transaction contract adds nullable `originalAmount`, `originalCurrency`,
`amountBase`, `fxRate`, and `fxRateDate`, plus `fxFeeAmountNative`, `isFxFee`,
and derived `valuationStatus: "valued" | "pending_fx"`.
`amountNative`/`currencyNative` retain their bank-posted meaning.

Phase 2 adds:

- `GET /api/insights/summary`
- `GET /api/insights/trends`
- `GET /api/insights/seasonality`
- `GET /api/insights/recurring`
- `PATCH /api/insights/recurring/:id`
- `GET /api/insights/findings`
- `PATCH /api/insights/findings/:id`
- `GET /api/insights/settings`
- `PATCH /api/insights/settings`
- `POST /api/insights/rebuild`

The range default is 12 months; supported presets are 3, 6, 12, 24, and all
history. List endpoints validate applicable date, account, category, merchant,
finding type/status, severity, cadence, and pagination filters. All monetary
values remain exact decimal strings.

## Behavioral Acceptance Gates

### Multi-currency ledger

- `original_amount` and `original_currency` are both null or both present; when
  present, original and posted amounts have the same flow sign.
- `amount_native` and `currency_native` remain immutable account-posted truth;
  reconciliation and deduplication do not depend on later original/FX/analytics
  enrichment.
- CAD is the only public reporting currency. A non-CAD switch request returns
  `409 base_currency_fixed`, while internal recovery rebuilds remain possible.
- Missing eligible CAD rates do not block native persistence or reconciliation.
  Affected rows report `pending_fx`, analytics become explicitly partial, and a
  later refresh fills only derived reporting fields.
- Rates use booked date or a nearest-prior date no more than seven days old;
  no fall-forward, stale substitution, or fabricated rate is accepted.
- Inline fee components are informational and never counted twice. Standalone
  fee rows remain separate reconciling transactions. Estimated markup excludes
  a known inline fee from its conversion basis.
- Mixed posted currencies in one account or statement fail validation and
  instruct the importer to use separate accounts.

### Insights and review workflow

- Insights default to 12 months and support 3-, 6-, 24-month, and all-history
  ranges, with exact monthly inflow, outflow, spending, and net cash flow plus
  account/category/merchant breakdowns and comparisons.
- Seasonality requires at least 12 months of source history. Shorter histories
  return an explicit insufficient-history result.
- Recurring detection uses 5–9, 12–16, 25–35, 80–100, and 330–400-day cadence
  windows; it requires three occurrences except that annual candidates may use
  two. Transfers and card payments are excluded from spending series. Expected
  next dates and overdue state are recurrence metadata, not forecasting.
- Price-increase findings require at least 5% and CAD 1 (or the equivalent
  comparison basis) by default and compare the newest amount with the prior
  stable median after removing an explicit inline fee.
- Balanced anomaly detection uses modified z-score `>= 3.5`, at least five
  prior comparable observations, and at least CAD 10 material difference;
  low/high sensitivity use `5.0`/CAD 25 and `2.5`/CAD 5. An interquartile-range
  fallback handles zero median absolute deviation.
- Near-duplicates require distinct transaction identities with the same
  account, merchant, posted currency, and absolute posted amount within three
  days; refunds, reversals, transfers, and payments are excluded.
- Findings expose calculation evidence and retain `new`, `confirmed`,
  `dismissed`, and `resolved` states. Dismissal persists until materially new
  evidence changes the detector fingerprint; user recurring corrections also
  survive refreshes.
- Readers see only an atomically published analytics snapshot. Run status,
  source watermark, counts, duration, and errors remain inspectable.

### Interfaces and experience

- Transaction responses add nullable `originalAmount`, `originalCurrency`,
  `amountBase`, `fxRate`, and `fxRateDate`, plus `fxFeeAmountNative`, `isFxFee`,
  and `valuationStatus`; all monetary values remain exact decimal strings.
- Insight list APIs validate supported date, account, category, merchant, type,
  status, severity, and pagination filters.
- The amount stack omits duplicate layers, labels original/posted/reporting
  values, and displays “CAD valuation pending” when required.
- `/insights` and its evidence/review controls work with keyboard navigation,
  responsive layouts, and reduced motion. Findings remain in-app only.

## Verification and Release Gates

- Preserve the Phase 0/1 golden closing balance of `2855.59` and zero-row repeat
  ingestion.
- Verify the Amex foreign-spend backfill preserves all existing posted and CAD
  values and creates no duplicate transaction.
- Add hand-calculated fixtures covering every trend, comparison, cadence,
  renewal, price increase, detector, zero-variance case, and partial-coverage
  calculation.
- Cover USD-original/TZS-posted, TZS-original/USD-posted, CAD-native, refunds,
  inline fees, standalone fee rows, malformed pairs, mixed-currency rejection,
  missing rates, and later FX backfill.
- On a synthetic 100,000-transaction ledger, warm materialized insight reads
  complete within one second and a full local rebuild within two minutes;
  incremental refresh touches only affected entities and periods.
- `make test`, `make check`, the production build, clean migrations and seed,
  and a disposable fresh-stack `make smoke` must pass before Phase 2 advances
  to review.
- Documentation, contracts, migration state, UI behavior, and the developer
  handoff must agree before closure.

## Review State

The real-bank gate is satisfied by the 11 sanitized I&M Tanzania TZS statements
accepted through `im_bank_tz_pdf_v1`, with exact reconciliation and zero-row
repeat ingestion. The PDFs remain local ignored acceptance inputs; sanitized
OCR-text derivatives provide CI-safe parser regression coverage. Generic USD
ledger behavior remains tested, but institution-specific USD statement support
is deferred until a sanitized sample is supplied and explicitly scheduled.

Phase 2 is `in_review`, not completed. Closure requires user review approval
and a final confirmation that the documented non-deferred gates remain green.
