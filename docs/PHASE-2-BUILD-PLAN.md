# Ledger — Phase 2 Build Plan

Current Phase: 2
Phase Status: completed
Jira Epic: N/A
Completed: 2026-07-25

> Phase 2 and the separately gated Phase 2.1 follow-up were approved
> independently on 2026-07-25. This plan is preserved as their historical
> implementation and acceptance record.

## Outcome

Phase 2 makes multi-currency ledger truth explicit and adds deterministic,
reviewable insights. Transactions preserve original purchase evidence, exact
account-posted values, and a nullable reporting valuation. The application
then materializes trends, seasonality, recurring activity, renewals, price
changes, anomalies, duplicates, reconciliation issues, coverage gaps, and
pending-FX findings without delegating arithmetic or detection to an LLM.

## Governing Decisions

- [ADR-0005](decisions/0005-three-layer-money-and-materialized-insights.md)
  defines the three monetary layers, Stage 1 fixed-CAD reporting, deferred
  valuation, deterministic materialization, and durable finding review state.
  ADR-0008 supersedes only its fixed-CAD clause for Phase 2.1.
- [ADR-0006](decisions/0006-im-bank-tanzania-pdf-and-deferred-usd-acceptance.md)
  defines the bounded local-OCR acceptance path for the supplied I&M Tanzania
  TZS statements and defers a named USD institution adapter.
- [ADR-0007](decisions/0007-market-scopes-and-progressive-disclosure.md)
  keeps one product and engine, adds explicit account market membership and a
  separate market profile, and defines fixed-CAD Stage 1 scope math.
- [ADR-0008](decisions/0008-configurable-cad-tzs-home-currency.md)
  defines the separately gated Phase 2.1 CAD/TZS home-currency rebuild and
  currency-fenced analytics rules.
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
13. Remediate review feedback with All/Canada/Tanzania scopes, scope-bearing
    analytics, progressive transaction disclosure, a three-section Home,
    Insights FX, Advanced operational controls, and four-item mobile navigation.
14. Gate Phase 2.1 separately: rebuild CAD/TZS reporting exclusively from
    immutable native money, freeze per-currency materiality thresholds, and
    publish only matching-currency analytics generations.

## Current Implementation Checkpoint

Backlog items 1–14 have implementation in the working tree. Migrations
`012`–`015` cover three-layer transaction persistence and Amex backfill,
deferred valuation, materialized analytics, explicit market membership and
scope identity, frozen threshold profiles, and currency-fenced CAD/TZS home
reporting. The shared/API contracts and application now include scoped reads,
canonical transaction conversion details, the simplified Home and Activity
experiences, Insights FX, Settings Advanced, and `/more`. Conventional XLSX
files retain the deterministic `generic_xlsx_v1` adapter that reuses the generic
CSV table rules; this is not a named institution adapter and does not satisfy
real-bank acceptance.

Incremental `analytics_refresh` runs detect transaction months changed since
the previous published source watermark, recompute all aggregate dimensions for
those months, and copy unaffected monthly rows into the next generation.
Recurring series and findings are recomputed from full source history
independently within `ALL`, `CA`, and `TZ` in both modes because their evidence
can cross month boundaries. Full mode recomputes all monthly periods plus those
scoped detectors. Either mode publishes one home-currency- and
threshold-policy-bound generation atomically and reports the affected-period
list in its job result.

Backlog item 12 is now implemented for the supplied I&M Tanzania TZS layout.
The versioned `im_bank_tz_pdf_v1` adapter uses bounded local Tesseract OCR and
accepts a transaction only after its amount agrees with the running-balance
delta, printed totals, and statement closing balance. All 11 supplied local
PDFs reconcile exactly: 41 transactions in total, five valid zero-activity
statements, and a 17-row statement that adds zero rows on repeat. The same
17-row file passes the encrypted object-store/web/worker/PostgreSQL path. A
named USD adapter is deliberately deferred under ADR-0006 and is not a review
or completion blocker.

A disposable database checkpoint applied migrations `001`–`015` from empty and
upgraded Phase 1 rows without changing immutable native truth or inferring
markets. It preserved legacy review state, exercised market-scope guards and
materialization, proved CAD→TZS→CAD rebuilding and switch auditing, fenced
publication by active currency, passed rollback/reapplication, and refused
rollback while TZS was active.

The checked-in `make benchmark-analytics` disposable benchmark passed with
exactly 100,000 synthetic transactions: the production full refresh took
`16.385s` (limit `120s`) and the slowest warm materialized read took `1.721ms`
(limit `1000ms`) before cleaning up its temporary database.

The final automated synthetic verification checkpoint passes `make check`
(Svelte zero errors/warnings, Ruff, strict mypy across 32 source/script files),
`make test` (23 shared, 63 web-server, 7 component, 20 Playwright, and 196
worker tests, plus 1 intentional worker skip), and `pnpm build`. A final isolated
Compose rerun rebuilt the current images, applied clean migrations `001`–`015`
plus seed, reconciled the Phase 0 six-row statement to `2855.59` with zero rows
on repeat, and passed explicit market scopes, USD/TZS three-layer evidence,
CAD/TZS round trips, FX evidence, analytics, and Insights review. The named
disposable project and volumes were removed without touching the default user
stack. Together with the real TZS acceptance evidence above, these results
returned Phase 2 to review. Phase 2 and the separately gated Phase 2.1
follow-up were then approved independently on 2026-07-25 after the permanent
regression gates were rerun.

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
- `GET /api/transactions/:id`
- `PATCH /api/settings`
- `POST /api/settings/base-currency`

Accounts, transactions, ordinary analytics, FX, and all Insights reads accept
an optional `market=CA|TZ`; omission means All. Account create/read/update
contracts expose `marketCode`, settings expose nullable `marketProfile`, and
account plus market filters are conjunctive.

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
- Stage 1 keeps CAD as the public reporting currency. Phase 2.1 permits only
  CAD or TZS through a confirmed Advanced maintenance action.
- Missing eligible reporting rates do not block native persistence or reconciliation.
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
- Price-increase findings require at least 5% and the active frozen profile's
  reporting-money floor. The seeded CAD `materiality-v1` floor is CAD `1.00`;
  the first TZS switch creates and persists its exact dated converted floor.
  Detection compares the newest amount with the prior stable median after
  removing an explicit inline fee.
- Balanced anomaly detection uses modified z-score `>= 3.5`, at least five
  prior comparable observations, and the active frozen profile's balanced
  floor. The seeded CAD `materiality-v1` low/balanced/high floors are CAD
  `25.00`/`10.00`/`5.00`; the first TZS switch converts and freezes their exact
  counterparts under the seven-day staleness rule. An interquartile-range
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
- Every analytics generation, aggregate, finding fingerprint, and evidence set
  is bound to its home currency and frozen threshold-policy version. Without a
  matching published generation, Insights returns `analytics_rebuilding` while
  ledger and account reads remain available.

### Market scopes

- Existing accounts upgrade with `market_code = NULL`; no value is inferred
  from currency or institution. New accounts require `CA` or `TZ`.
- All contains every account, including unassigned accounts. Canada/Tanzania
  include only explicitly assigned accounts, including foreign-currency accounts.
- Account and market filters are conjunctive. A scope change clears a selected
  account that is absent from the new scope.
- All, CA, and TZ monthly aggregates, recurring series, and findings are built
  from their scoped source transactions. Scope participates in fingerprints
  and durable review state.
- Resolution order is URL, remembered browser preference, `marketProfile`, then
  All. User scope changes update both URL and browser storage.

### Interfaces and experience

- Transaction responses add nullable `originalAmount`, `originalCurrency`,
  `amountBase`, `fxRate`, and `fxRateDate`, plus `fxFeeAmountNative`, `isFxFee`,
  and `valuationStatus`; all monetary values remain exact decimal strings.
- Insight list APIs validate supported date, account, category, merchant, type,
  status, severity, and pagination filters.
- Activity rows show only the account-posted amount. `FX`, `Converted`, and
  `Pending` indicators open a keyboard-accessible responsive audit drawer with
  original/posted/reporting money, rates, fees, markup, and both balances.
- Home contains only scoped reporting net worth, scoped native account balances,
  and recent posted activity. Balance/cash-flow and aggregate FX move to
  Insights; operational health, sensitivity, and rebuild controls move to
  Settings Advanced.
- Mobile navigation is Home, Activity, Insights, More. `/more` links Accounts,
  Categories, Imports, and Settings. Imports uses the active market scope.
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
- Cover unassigned All-only accounts, explicit TZ USD accounts, scoped totals
  and pagination, every analytics dimension, recurring/finding isolation,
  scope-safe offline keys, URL/browser persistence, and stale account filters.
- Cover CAD→TZS→CAD, identity and missing rates, no stale reporting-value reuse,
  advisory-lock serialization, matching-currency publication, frozen thresholds,
  recurring override conversion, maintenance state, and stale-run rejection.
- On a synthetic 100,000-transaction ledger, warm materialized insight reads
  complete within one second and a full local rebuild within two minutes;
  incremental refresh touches only affected entities and periods.
- `make test`, `make check`, the production build, clean migrations and seed,
  and a disposable fresh-stack `make smoke` must pass before Phase 2 advances
  to review.
- Documentation, contracts, migration state, UI behavior, and the developer
  handoff must agree before closure.

## Closure State

The real-bank gate is satisfied by the 11 sanitized I&M Tanzania TZS statements
accepted through `im_bank_tz_pdf_v1`, with exact reconciliation and zero-row
repeat ingestion. The PDFs remain local ignored acceptance inputs; sanitized
OCR-text derivatives provide CI-safe parser regression coverage. Generic USD
ledger behavior remains tested, but institution-specific USD statement support
is deferred until a sanitized sample is supplied and explicitly scheduled.

ADR-0007 review remediation and every expanded gate above passed. Phase 2 was
approved and completed on 2026-07-25. ADR-0008's Phase 2.1 home-currency work
was evaluated as a separate gate and approved independently on the same date;
its approval did not retroactively change the Phase 2 scope. The permanent
Phase 0–2.1 regression gates carry forward into Phase 3.
