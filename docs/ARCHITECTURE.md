# Ledger — Architecture & System Design

> Long-term target: a self-hostable, multi-institution, multi-currency personal
> finance analytics app that normalizes supported statements into one canonical
> ledger, computes money deterministically, and later adds a grounded
> natural-language layer.

**Status:** Phase 1 implementation is in review with test/check/build/fresh-smoke
acceptance recorded; Phases 2–4 remain design scope.
**Audience:** the person building it (you).
**Author's stance:** every tech choice below is argued, not defaulted. Where I
picked a non-obvious tool, there's an ADR explaining what I rejected and why.

---

## 1. Goals & non-goals

### Goals
- **Own your data.** One canonical ledger across every account you have, regardless of bank or currency.
- **Deploy it.** Runs as a hosted web app, installable on phone and laptop (PWA). Not tied to any chat or notebook.
- **Analyze deeply.** Cash flow, trends, seasonality, recurring detection, anomalies, discrepancies, FX exposure, reconciliation, forecasts — not just subscriptions.
- **Ask it things.** Natural-language questions answered from *computed* numbers, with every figure traceable to a query, not a hallucination.
- **Right-sized AI.** AI only where language/ambiguity live. Never in the math.
- **Extensible ingestion.** Adding a new bank or format is config + one AI-assisted mapping pass, not a code rewrite.

### Non-goals (v1)
- Not a budgeting-envelope app, not a bill-pay tool, not a bank aggregator with live API links (Plaid-style) — that's a possible v3, but statement ingestion is the trust-minimizing, bank-agnostic starting point.
- Not multi-tenant SaaS at launch. Phase 1 is a single-user, single-ledger local
  application; authentication, tenant ownership, billing, and organizations are
  later concerns.
- No tax filing, no investment portfolio pricing (v2+).

---

## 2. Design principles

These are load-bearing. Every later decision derives from them.

1. **Money is computed, never generated.** LLMs never do arithmetic or produce a figure that reaches a balance, total, or chart. All financial values come from deterministic code over the canonical ledger.
2. **AI proposes, deterministic code disposes.** AI output is always a *proposal* (a category, a column mapping, a query spec) that is validated by code before it has any effect. Invalid proposals are rejected, not trusted.
3. **Grounded answers only.** The NL layer answers strictly from tool results (executed queries). If a number isn't in a tool result, it doesn't appear in the answer. No free-text finance.
4. **Run AI once, then cache and learn.** The expensive AI passes (format mapping, categorizing a new merchant) happen once per *novel* input, then the learned result is persisted and reused deterministically forever.
5. **Model tiering by task.** Cheap model for high-volume small jobs; capable model for genuinely hard extraction/planning. (Table in §10.)
6. **Every transaction is idempotent and auditable.** Re-uploading the same or overlapping statement never double-counts. Every derived value can be traced to source rows.
7. **The base currency is a lens, not a rewrite.** Original amount + currency are immutable truth. The base-currency view is a derived layer you can recompute or change without touching source data.

### Notable non-default choices (called out because you asked)
- **Polars, not pandas**, for the analytics/ingestion worker — lazy execution, faster on statement-sized data, cleaner API, and it forces explicit schemas (good for financial correctness).
- **SvelteKit, not Next/React**, as the primary frontend recommendation — smallest runtime for a mobile PWA, one framework for UI + server routes, less ceremony for a solo builder. React/Next is the documented fallback if ecosystem size matters more to you.
- **A constrained query DSL, not text-to-SQL**, for the NL layer — the LLM emits a validated JSON query spec, never raw SQL. Safety + correctness.
- **Postgres-backed job queue for MVP, not Redis/Celery** — one less piece of infra until volume justifies it.
- **uPlot for the dense time-series, ECharts for everything else** — not Recharts. uPlot renders tens of thousands of points on a phone without jank; ECharts covers the richer exploratory charts with one dependency.

---

## 3. System architecture (Phase 1)

```mermaid
flowchart TB
    subgraph Client["Clients — PWA (phone + laptop)"]
        UI["SvelteKit app<br/>dashboard · transactions · accounts · categories · imports"]
    end

    subgraph Edge["App / API tier — TypeScript"]
        API["API + BFF<br/>validation · reads · orchestration"]
    end

    subgraph Work["Ingestion & services — Python worker"]
        ING["Ingestion pipeline<br/>parse · normalize · FX · reconcile"]
        SVC["Service jobs<br/>categorize · FX refresh · base rebuild"]
    end

    subgraph AI["AI providers (bounded)"]
        LLM["LLM: redacted column mapping<br/>and categorization tail"]
    end

    subgraph Data["State"]
        PG[("Postgres<br/>ledger + pgvector")]
        OBJ[("Object store<br/>raw statement files, encrypted")]
        FX["FX rates cache"]
    end

    UI <--> API
    API --> PG
    API -- enqueue job --> PG
    ING -- poll jobs --> PG
    SVC -- poll jobs --> PG
    ING --> OBJ
    ING --> LLM
    ING --> PG
    SVC --> LLM
    SVC --> FX
    SVC --> PG
    ING --> FX
```

**Component responsibilities**

| Component | Language | Responsibility |
|---|---|---|
| **Client (PWA)** | SvelteKit/TS | Five focused routes, charts, narrowly bounded offline dashboard reads, and responsive installability. |
| **API / BFF** | Node/TS | Request validation, encrypted uploads, parameterized reads, deterministic analytics, account/taxonomy writes, and job orchestration. |
| **Python worker** | Python | Parse CSV/XLSX/PDF tables/OFX, normalize, deduplicate, FX-stamp, reconcile, categorize the unknown tail, refresh rates, and rebuild base values. |
| **Postgres** | — | Source of truth: canonical ledger, categories, learned mappings, FX rates, jobs, embeddings (pgvector). |
| **Object store** | — | Application-encrypted raw uploads through the S3 API; MinIO in the local stack. |

**Why this split (polyglot on purpose):** the two hard problems are (1) turning
arbitrary bank PDFs/CSVs into clean rows and (2) statistical analytics. Python
owns both — `pdfplumber`/`camelot` for PDF tables, `polars` for fast columnar
analytics, `statsmodels`/`scikit-learn` for trend and anomaly work. Everything
user-facing and orchestration-shaped is TypeScript so the client and API share
one type system. This is a deliberate trade: one extra runtime in exchange for
the right tool on each side. The deeper analytics engine and grounded ask
service described in §§8–9 are Phase 2 and Phase 3 design, not current Phase 1
components.

---

## 4. Canonical data model

The whole point: no matter which bank or currency a statement comes from, it
lands in **one** shape. Everything downstream reads canonical rows only.

```mermaid
erDiagram
    INSTITUTION ||--o{ ACCOUNT : issues
    ACCOUNT ||--o{ STATEMENT : has
    ACCOUNT ||--o{ TXN : has
    STATEMENT ||--o{ TXN : contains
    TXN }o--|| CATEGORY : classified_as
    TXN }o--|| MERCHANT : from
    MERCHANT ||--o{ MERCHANT_CATEGORY_MAPPING : learned_for
    CATEGORY ||--o{ MERCHANT_CATEGORY_MAPPING : selected_by
    MERCHANT ||--o{ CATEGORIZATION_PROPOSAL : proposed_for
    INSTITUTION ||--o{ ADAPTER : parsed_by

    ACCOUNT {
        uuid id
        uuid institution_id
        string display_name
        string kind  "credit_card | chequing | savings | wallet"
        string native_currency
        string account_ref_masked
        numeric credit_limit
    }
    STATEMENT {
        uuid id
        uuid account_id
        date period_start
        date period_end
        numeric opening_balance
        numeric closing_balance
        string currency
        string source_file_key
        string reconcile_status "pending | ok | gap | mismatch"
    }
    TXN {
        uuid id
        uuid account_id
        uuid statement_id
        date booked_date
        date posted_date
        string description_raw
        uuid merchant_id
        uuid category_id
        numeric amount_native   "signed; +charge / -credit"
        string  currency_native
        numeric amount_base
        string  currency_base
        numeric fx_rate
        date    fx_rate_date
        string  external_ref
        string  dedup_hash
        string  direction "debit | credit | payment | fee | refund | interest"
        string  category_source "fallback | rule | ai | user_merchant | user_transaction"
        numeric category_confidence
        jsonb   enrichment "foreign_spend, flags, confidence"
    }
    MERCHANT {
        uuid id
        string canonical_name
        string normalized_key
        vector embedding
    }
    MERCHANT_CATEGORY_MAPPING {
        uuid merchant_id
        string flow_type
        uuid category_id
        string source "ai | user_merchant"
        numeric confidence
    }
    CATEGORIZATION_PROPOSAL {
        uuid id
        uuid opaque_key
        uuid merchant_id
        string flow_type
        uuid proposed_category_id
        string proposed_category_name
        string proposed_category_kind
        numeric confidence
        string status "pending | accepted | rejected"
        string provider
        string model
        jsonb raw_assignment
        datetime reviewed_at
    }
    CATEGORY {
        uuid id
        uuid parent_id
        string name
        string kind "spend | income | transfer | fee"
        datetime archived_at
        boolean is_protected
    }
    ADAPTER {
        uuid id
        uuid institution_id
        string format "pdf | csv | xlsx | ofx"
        jsonb column_map
        jsonb detection_fingerprint
        int   version
    }
    FX_RATE {
        string base
        string quote
        date   as_of
        numeric rate
        string source
    }
    LEDGER_SETTINGS {
        boolean singleton
        string base_currency
        datetime updated_at
    }
    JOB {
        uuid id
        string kind "ingest | categorize | fx_refresh | base_currency_rebuild"
        string status "queued | claimed | done | failed | needs_ai"
        string deduplication_key
        int retry_count
        int max_retries
    }
```

**Design notes**

- **Sign convention is fixed at ingestion**, per account kind. Credit-card charges are `+`, payments/credits `-`; for a chequing account you may invert. The `direction` enum carries the semantic meaning so analytics never has to guess from sign alone.
- **`amount_native` is immutable truth.** `amount_base` / `fx_rate` are derived and recomputable. Change your base currency → rebuild the base column, source rows untouched.
- **`dedup_hash`** = hash of `(account_id, booked_date, amount_native, currency_native, normalized_description, external_ref)`. This is what makes re-uploads and overlapping statements safe.
- **OFX FITID** is also authoritative within an account: migration `009`
  uniquely constrains `(account_id, external_ref)` only for OFX-enriched rows.
- **`enrichment` JSONB** holds format-specific extras (Amex "Foreign Spend Amount", flags like `possible_duplicate`, categorization `confidence`) without schema churn.
- **`account_ref_masked`** — migration `011` permits only a non-digit masked
  label plus the final 2–6 digits (for example, `••••71001`). Full or formatted
  account/card numbers fail both request and database validation. (Security,
  §13.)
- **`credit_limit`** is optional, positive, card-only, and denominated in the
  account's native currency. It is utilization metadata, never an asset.
- **Category provenance** makes user choices durable and prevents a later AI
  job from overwriting a transaction-specific correction.
- **Category kind becomes structural once used.** Migration `010` prevents
  changing `kind` after a category is referenced by a transaction, mapping, or
  proposal, or after it has children; unused leaf categories remain editable.
- **pgvector on `MERCHANT.embedding`** remains available for a later semantic
  matcher; Phase 1 uses exact learned merchant-and-flow mappings.

---

## 5. Ingestion pipeline

The extensibility engine. Adding "a different bank with a different currency" is
the main thing this must make cheap.

```mermaid
sequenceDiagram
    participant U as Client
    participant API as API
    participant Q as Job table (PG)
    participant W as Python worker
    participant AI as LLM
    participant DB as Postgres

    U->>API: upload statement file(s)
    API->>OBJ: store raw file (encrypted)
    API->>Q: enqueue ingest job
    API-->>U: job accepted (id)
    W->>Q: claim job
    W->>W: 1. detect format + institution (fingerprint)
    alt known adapter
        W->>W: 2. parse with adapter (deterministic)
    else unknown format
        W->>AI: 2. infer column map (once)
        AI-->>W: proposed mapping
        W->>W: validate mapping on sample rows
        W->>DB: save new ADAPTER (version++)
    end
    W->>W: 3. normalize → canonical rows
    W->>W: 4. FX-stamp each row
    W->>W: 5. merchant normalize + deterministic account-aware rules
    W->>W: 6. dedup by hash
    W->>W: 7. reconcile vs statement opening/closing
    W->>DB: upsert txns + statement + flags
    W->>Q: enqueue novel categorization / FX work after persistence
    W-->>U: polled result, N new / M skipped
```

### Format detection & adapters
- **Detection**: file extension → structural fingerprint (header row signature for CSV/XLSX; text layout signature for PDF). A fingerprint maps to an `ADAPTER` row. No fingerprint match → unknown path.
- **Adapter** = a saved `column_map` + detection fingerprint per `(institution, format)`. Deterministic once it exists.
- **Parsers by format:**
  - **CSV/XLSX** → Polars readers. Header row located by scanning for the first row containing date+amount-like columns (your Amex export buries it on row 7 — the detector handles that generically).
  - **PDF** → deterministic `pdfplumber` table extraction. An irregular or
    rejected table reports `needs_ai`, but Phase 1 never sends PDF content to a
    provider. Vision/OCR fallback remains Phase 4.
  - **OFX/QFX** → deterministic OFX1 SGML and OFX2 XML bank/card parsing.
    Investment statements are unsupported. FITID is required and unique within
    an account's OFX-enriched transactions; statement currency and masked
    account identity must match the selected account.

### AI-assisted column mapping (runs once per new format)
When an unknown CSV/XLSX arrives, send **only header names + at most five
structurally redacted sample rows** (not the whole file) to the LLM with a
strict output schema: map each source
column to a canonical field (`booked_date`, `amount`, `currency`, `description`,
`external_ref`, …) plus detected date format, decimal/thousands separators, and
sign convention. Deterministic code validates column existence, amount versus
debit/credit exclusivity, account/currency/sign compatibility, every parsed row,
and reconciliation. Only a valid mapping is persisted as an `ADAPTER`; invalid
output writes no financial rows and returns `needs_ai`. Every future matching
file is then deterministic and provider-free.

### Compatibility learning and canonical-schema evolution

The learning layer adapts source statements to Ledger; it does not let a model
silently mutate Ledger's financial schema. A new statement follows this
compatibility ladder:

1. **Known structure:** a fingerprint matches a saved adapter. Parse locally
   with no provider call.
2. **New layout, known concepts:** the file contains the canonical concepts
   Ledger already understands, but uses different headers, ordering, date
   notation, decimal notation, or debit/credit representation. AI may propose
   the column correspondence; local code derives financial semantics, parses
   every row, verifies account and currency compatibility, and reconciles the
   statement before versioning and caching the adapter.
3. **Ambiguous or invalid layout:** required evidence is missing, multiple
   interpretations remain plausible, or reconciliation fails. Write no
   statement or transaction rows, preserve the encrypted source, and return
   `needs_ai` with a reason suitable for a mapping-review surface.
4. **New financial concept:** the statement contains information the canonical
   model cannot represent without loss (for example, multiple balances with
   distinct meanings, installment-plan state, or a new account/product type).
   AI may produce a structured compatibility report, but it may not add a
   column, migration, account kind, or arithmetic rule. Schema evolution
   requires an ADR, migration, deterministic parser/normalizer changes,
   sanitized fixtures, reconciliation tests, and an adapter version bump before
   the retained source is replayed.

The persisted learning unit is an adapter identified by institution, file
format, structural fingerprint, account kind, and native currency. Transaction
values and descriptions are not part of the fingerprint. A changed bank export
therefore creates a new adapter version instead of weakening a known mapping.
Adapters must remain inspectable, reversible, and auditable: record the
fingerprint, mapping, version, validation outcome, creation source, and
supersession relationship.

Phase 1 implements the known-structure and validated new-layout paths and fails
closed to `needs_ai`. A user-facing mapping editor/approval flow, compatibility
reports for genuinely new concepts, adapter rollback/supersession controls, and
safe replay after schema evolution belong to Phase 4 ingestion hardening.

### Idempotency, dedup, reconciliation
- **Upsert on `dedup_hash`.** New hash → insert. Seen hash → skip (report as "already recorded").
- **OFX identity:** the statement FITID is stored as `external_ref`; an OFX-only
  partial unique index enforces `(account_id, FITID)` independently of the
  generic content hash.
- **Reconciliation** (a first-class discrepancy check): for each statement, assert `opening_balance + Σ amount_native == closing_balance`. Mismatch → flag `reconcile_status = mismatch` and surface it (missing rows, OCR error, or a genuine bank discrepancy). Overlapping statements with a **gap** in coverage → `gap`, so trends never silently interpolate over missing months.
- **Position anchors:** non-null source-reported balances with status `ok`,
  `gap`, or `pending` may establish a position. `pending` represents one-sided
  evidence (for example, OFX with only a closing balance) that cannot satisfy a
  two-sided arithmetic reconciliation; it is not labeled `ok`. A `mismatch`
  balance is rejected as an anchor.
- **Post-persistence isolation:** categorization and FX-refresh enqueueing happens
  after financial persistence. Provider or secondary queue failures cannot roll
  back a successfully reconciled import.

---

## 6. Multi-currency & FX

- **Store three things per txn:** native amount+currency (truth), the FX rate used, and the base-currency amount (derived). Plus `fx_rate_date` and source.
- **Rate source:** Frankfurter v2, whose public API can also be self-hosted and
  covers CAD, USD, and TZS. Accept the requested date or a recorded prior date
  no more than seven days old; otherwise fail closed.
- **One staleness policy:** both worker provider/cache code and web account,
  transaction, net-worth, and FX reads use the validated
  `FX_MAX_STALENESS_DAYS` configuration. Startup rejects values outside `0..7`.
- **Rate is stamped at `booked_date`**, cached in `FX_RATE`. Backfill job pulls missing dates.
- **Base currency is a single-ledger database setting and switchable.** Changing
  it prefetches every required rate and atomically rebuilds `amount_base` across
  all rows from immutable native amounts. Ingestion and the final switch use the
  same advisory lock, so readers never observe mixed currencies.
- **FX analytics are deterministic:** when foreign-spend evidence and a cached
  market rate both exist, compare the card's applied rate with the market rate
  and expose the implied fee/markup. Otherwise those fields remain absent.

---

## 7. Merchant normalization & categorization

A hybrid pipeline that gets cheaper and more accurate the more you use it.

```mermaid
flowchart LR
    raw["raw description"] --> A{exact match<br/>in merchant map?}
    A -- yes --> done["assign merchant + category"]
    A -- no --> B{rule / regex<br/>dictionary hit?}
    B -- yes --> learn
    B -- no --> D["LLM tail:<br/>name + category proposal"]
    D --> validate{valid category?<br/>confidence ok?}
    validate -- yes --> learn["persist mapping<br/>(now deterministic)"]
    validate -- no --> review["queue for your review"]
    learn --> done
```

- **Taxonomy** is hierarchical and **user-editable**; your overrides are permanent and always win.
- **The LLM only sees the unknown tail** — opaque request keys, normalized
  merchant text, a coarse flow type, and the current taxonomy. It receives no
  amounts, dates, account/transaction IDs, balances, or statement content.
- **Confidence + review queue:** validated existing categories at or above the
  configured threshold apply automatically. Low-confidence guesses and all new
  category proposals wait for review. You confirm once; it learns.
- **Override precedence:** transaction-specific user choice → user merchant/flow
  mapping → learned AI mapping → deterministic account-aware rule → `Other`.
- **Review surfaces:** the API exposes distinct unresolved merchant/flow pairs
  separately from low-confidence/new-category proposals, so the Categories page
  can show both the remaining workload and audited decisions.

---

## 8. Analytics

Phase 1 computes four read views directly and deterministically over the
canonical ledger:

- **Balance:** native/base position series with opening balances converted and
  credit-card liabilities negated for consolidation. Non-null `ok`, `gap`, and
  one-sided `pending` reported balances may anchor positions; `mismatch` cannot.
- **Cash flow:** account-kind-aware inflow, outflow, and net with transfers and
  card payments excluded from double counting. Card payments remain visible as
  a separate neutral series so imported payment activity is auditable without
  being mislabeled as income or expense.
- **Net worth:** current assets, liabilities, and net worth from imported asset
  and credit-card accounts. Missing verified balances or usable current rates
  are excluded with reasons and make the response `partial`.
- **FX:** foreign-spend evidence compared with the applicable cached market rate
  when both inputs exist.

Account reads also compute exact per-card and aggregate utilization. Transaction
reads return native and base values plus a running balance calculated for each
ordered transaction row, not one shared end-of-day value.

Phase 2 is where trends, seasonality, recurring/renewal detection, statistical
anomalies, duplicate-charge analysis, and materialized heavy aggregates belong.
Forecasting remains Phase 4. Those future analytics must retain the same exact
money, polarity, valuation, and reconciliation invariants.

---

## 9. "Ask it things" — Phase 3 design

This subsystem is not implemented in Phase 1. Its trust rule remains:
**the model
never sees the database and never emits a number.** It translates and narrates;
code computes.

```mermaid
flowchart TB
    q["your question<br/>'how much did I spend on travel in TZS last quarter vs before?'"]
    q --> plan["LLM: question → QUERY SPEC (JSON)<br/>metrics, filters, group-by, time range, compare"]
    plan --> val{validate spec<br/>against schema + catalog}
    val -- invalid --> clarify["ask you to clarify /<br/>repair spec"]
    val -- valid --> exec["deterministic executor<br/>→ parameterized SQL / aggregate read"]
    exec --> res["result set (real numbers)"]
    res --> narr["LLM: narrate result<br/>(only numbers from result set)"]
    narr --> ans["answer + the table/chart it's based on"]
```

- **Constrained query DSL, not text-to-SQL.** The LLM outputs a typed JSON spec (allowed metrics, dimensions, filters, time grains, comparisons). A validator rejects anything referencing unknown fields or unsafe operations. A query builder turns the spec into parameterized SQL. **No model-authored SQL ever runs.** This kills injection, hallucinated columns, and silent wrong math in one move.
- **Tool-using agent.** The ask service exposes a small, closed tool set: `run_query(spec)`, `get_timeseries(...)`, `list_anomalies(...)`, `describe_schema()`. The agent may only call these. Every figure in the final answer maps to a tool result — and the UI shows that result (table/chart) beside the prose, so answers are auditable.
- **Ambiguity → clarify, not guess.** "Last quarter" with mixed currencies → the spec makes the base-currency and period explicit, or the agent asks.
- **Everything the ask-layer can answer, the dashboard could show** — it's the same executor underneath. The NL bar is a fast path, not a separate truth.

---

## 10. Where AI is used — the "right amount" matrix

The explicit answer to "just the right amount of AI for just the right amount of
things." If a row could be deterministic, it is.

| Task | Deterministic or AI | If AI: model tier | Frequency | Cached / learned |
|---|---|---|---|---|
| Arithmetic, balances, aggregates, FX conversion | **Deterministic** | — | every read | n/a |
| Recurring detection, anomalies, trends (Phase 2) | **Deterministic** | — | on ingest | materialized |
| CSV/XLSX parsing (known format) | **Deterministic** | — | every file | adapter cached |
| **Column mapping (new/unknown format)** | AI | capable (Sonnet-class) | once per new format | **saved as adapter** |
| **PDF extraction (irregular layout only)** | Deferred to Phase 4 | capable, vision | parser fallback | raw file retained |
| Merchant categorization — head (known) | **Deterministic** | — | every txn | rule map |
| **Merchant categorization — unknown tail** | AI | cheap (Haiku-class) | once per new merchant | **persisted as rule** |
| **NL question → query spec (Phase 3)** | AI | capable | per question | prompt-cached |
| **Result narration (Phase 3)** | AI | cheap | per question | — |
| Insight summaries (later phase) | AI | cheap | on demand | — |

**Cost posture:** Phase 1 recurring AI cost is limited to novel categorization
work; unknown-format mapping runs once per validated fingerprint. Bulk ingestion
of a known bank costs zero AI. Interactive-question cost begins only if the
Phase 3 ask layer is built.

**Data-to-AI boundary (privacy):** the Phase 1 model sees only redacted headers
plus at most five sample rows for a new tabular format, or the minimized
merchant proposal payload described above. Account-like identifiers are masked.
Full statements, raw balances, and PDFs are not sent in Phase 1.

---

## 11. Phase 1 API surface

REST/JSON with shared TypeScript/Zod contracts and explicitly mirrored Python
Pydantic models where worker results cross the boundary. All money values are
exact decimal strings.

```
GET    /api/health
POST   /api/ingest
GET    /api/jobs
GET    /api/jobs/:id
GET    /api/accounts
POST   /api/accounts
PATCH  /api/accounts/:id
GET    /api/institutions
POST   /api/institutions
PATCH  /api/institutions/:id
GET    /api/transactions
PATCH  /api/transactions/:id
GET    /api/categories
POST   /api/categories
PATCH  /api/categories/:id
GET    /api/categories/unresolved
GET    /api/categories/proposals
PATCH  /api/categories/proposals/:id
POST   /api/categories/categorize
GET    /api/analytics/:view     balance | cashflow | net-worth | fx
GET    /api/settings
POST   /api/settings/base-currency
```

The transaction and job query schemas validate URL-backed filter, sort, and
pagination parameters. A future `/api/ask` surface belongs to Phase 3 and is not
part of the Phase 1 server.

---

## 12. Clients

- **SvelteKit PWA** — installable on iOS/Android/desktop from one codebase. The
  shared shell provides Dashboard, Transactions, Accounts, Categories, and
  Imports navigation.
- **Narrow offline boundary:** shell assets and `/` use the shell cache. Only
  `/api/analytics/balance` and `/api/analytics/cashflow` use a network-first
  private-read cache. Net-worth responses are never service-worker cached.
  Other page navigations, accounts, FX, transactions, categories, imports,
  jobs, and every write are also uncached by the service worker.
- **Charts:** **uPlot** for the running-balance and dense time-series (fast on mobile, tiny); **ECharts** for category/treemap/heatmap/comparison views. Deliberately not a single heavyweight React chart lib.
- **Ask bar (Phase 3):** if built, it should return prose plus its source
  table/chart and a query-inspection affordance; it is not a Phase 1 client
  element.
- **Responsive-first**, keyboard-accessible, respects reduced-motion.

---

## 13. Security & privacy

Financial data — treat it like it matters, even single-user.

- **Authentication boundary:** Phase 1 has no authentication and must be treated
  as a local single-user service. Passkeys/WebAuthn and multi-user authorization
  are later deployment work, not current controls.
- **Encryption:** raw statement files are encrypted in the application before
  object storage. TLS and database/storage-volume encryption are deployment
  requirements outside the local Compose implementation. The application
  encrypts raw files
  with a versioned AES-256-GCM envelope before MinIO sees them, as recorded in
  [ADR-0001](decisions/0001-application-layer-statement-encryption.md). Host and
  storage encryption remain defense in depth.
- **PII minimization:** store only masked account references. Shared request
  validation and migration `011` require a masked label plus a 2–6 digit suffix;
  full/formatted account or card numbers are rejected. Never place references in
  URLs or query strings. Resource UUIDs may appear in API paths.
- **Least-privilege AI:** per §10, Phase 1 sends only minimized categorization
  payloads or redacted tabular samples. PDF content is never sent. Any opt-in
  PDF vision/local-OCR path is Phase 4 work.
- **Secrets** in a manager (not env files in the repo); rotate provider keys.
- **Tenant isolation:** Phase 1 has no user/tenant table or row-level security.
  Those must be designed together with authentication before multi-user use.
- **Auditability:** every derived number traces to source rows; categorization
  proposals retain provider/model, opaque request identity, validated assignment,
  status, and review timestamp. Column mappings are stored only after validation.

---

## 14. Deployment & infrastructure

**Recommended topology (container-based, self-hostable):**

| Piece | Choice | Why |
|---|---|---|
| Frontend + API | One SvelteKit deployment (Node adapter) | UI + server routes together; simplest for solo |
| Python worker | Separate container | Long-running ingestion/analytics; scales independently |
| Job queue | **Postgres table + worker poll (MVP)** → Redis/queue later | Skip Redis until volume needs it |
| Database | Managed Postgres (Neon/Supabase) or self-hosted PG + pgvector | Source of truth |
| Object storage | Cloudflare R2 / S3, or a local volume when self-hosted | Encrypted raw files |
| Host | **Fly.io / Railway / Render**, or your own VPS via Docker Compose | Runs containers + PG + volumes in one place; self-hostable |

- **Self-host path:** a single `docker-compose` (web, worker, postgres, minio-for-objects) so you can run the whole thing on your own box — consistent with owning your financial data.
- **CI/CD:** build + typecheck + run the reconciliation/analytics test suite (golden-file tests on sample statements) before deploy. **Financial math must have regression tests** — a fixture statement with a known correct closing balance and category totals that CI asserts on every change.
- **Observability:** structured logs, job success/failure metrics, and a per-ingest reconciliation report. Alert on `reconcile_status = mismatch` spikes (parser regressions).

---

## 15. Build roadmap

Sequenced so you always have a working, useful thing.

**Phase 0 — Ledger core (no AI).**
Canonical schema, Amex XLSX + generic CSV adapters, dedup, FX stamping,
running balance, reconciliation, basic dashboard. *This alone replaces the chat
artifact and works across CSV banks.*

**Phase 1 — Multi-bank + multi-currency for real.**
OFX/QFX parser, AI column-mapper for unknown formats, base-currency switching,
FX-fee analytics, CAD/USD/TZS accounts, account/limit management, deterministic
net worth, category taxonomy, learned mappings, and user overrides. The client
is split into Dashboard, Transactions, Accounts, Categories, and Imports.

**Phase 2 — Analytics depth.**
Trends/seasonality, anomaly + discrepancy suite, recurring/renewal/price-hike
detection and materialized aggregates.

**Phase 3 — Ask it things.**
Query DSL + validator + executor, the tool-using agent, narration, the ask-bar
UI with grounded results.

**Phase 4 — Ingestion hardening + polish.**
PDF extraction (deterministic + AI fallback + local-model option), forecasts,
offline hardening, and deployment polish.

---

## 16. Resolved Phase 1 decisions

1. Keep the Python worker plus SvelteKit web/API split.
2. Keep the self-hosted Docker Compose path and single-user product boundary.
3. Use CAD as the initial switchable base with USD and TZS native accounts.
4. Use Frankfurter v2 for the cached FX feed.
5. Use Anthropic first behind the provider interface, with minimized structured
   inputs and reviewed taxonomy changes per ADR-0003.
6. Keep irregular-PDF AI extraction and local OCR/model work in Phase 4.
7. Move imported-account net worth into Phase 1 per ADR-0004; manual assets and
   debts remain deferred.

---

*Everything here is designed so the boring 95% is deterministic, tested, and
free, and the AI is concentrated in the 5% where language and ambiguity actually
live — reading a new bank's format, naming an unknown merchant, understanding a
question. That's the "right amount."*
