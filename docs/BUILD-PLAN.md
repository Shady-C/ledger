# Ledger — Phase 0 Build Plan

**Status:** Implemented and in review as of 2026-07-24. Automated validation
uses three sanitized, structurally representative Amex workbooks because no
private statement files are stored in this repository. The owner's original
three exports also passed local acceptance on 2026-07-24: 193 canonical rows,
three successful reconciliations, a `2855.59` closing balance, and zero rows
added by an identical repeat import.

> Companion to `ARCHITECTURE.md`. This is the first executable slice: a
> **self-hosted, end-to-end vertical** that ingests Amex statements,
> stores them in the canonical ledger, computes balances and cash flow
> deterministically, and shows them in a SvelteKit PWA. No AI is in the critical
> path yet — the provider gateway is scaffolded but idle. AI-assisted ingestion
> (column mapper, PDF fallback) lands in Phase 1, immediately after.

**Locked decisions this plan honors:** polyglot (TS app + Python/Polars worker) ·
SvelteKit · fully self-hosted (`docker-compose`) from day one · PDF ingestion
early · CAD base with TZS/USD native · Anthropic behind a swappable
`LLMProvider` interface · cloud extraction for now.

**Phase 0 definition of done:** `docker compose up`, open the app, upload three
validated Amex `.xlsx` files, and see the exact reconciled running balance
(**closing $2,855.59**), cash-flow chart, and a searchable transaction table —
with CI asserting those numbers on every commit.

---

## 1. Monorepo layout

```
ledger/
├─ docker-compose.yml          # web · worker · postgres · minio
├─ .env.example                # secrets template (never commit real .env)
├─ Makefile                    # up / down / migrate / seed / test
├─ packages/
│  └─ shared-types/            # canonical types, query DSL schema (TS source of truth)
│     └─ src/{transaction,account,query-spec}.ts
├─ apps/
│  └─ web/                     # SvelteKit — UI + BFF/API routes
│     ├─ src/routes/
│     │  ├─ +page.svelte           # dashboard
│     │  ├─ api/ingest/+server.ts   # POST upload → enqueue
│     │  ├─ api/jobs/[id]/+server.ts
│     │  ├─ api/accounts/+server.ts
│     │  ├─ api/transactions/+server.ts
│     │  └─ api/analytics/[view]/+server.ts
│     ├─ src/lib/
│     │  ├─ db.ts                  # pg client + query executor
│     │  ├─ charts/                # uPlot (balance) + ECharts (rest)
│     │  └─ components/
│     └─ svelte.config.js          # adapter-node (self-host)
├─ services/
│  └─ worker/                  # Python — ingestion + analytics
│     ├─ pyproject.toml            # polars, pdfplumber, camelot, psycopg, pydantic
│     ├─ worker/
│     │  ├─ main.py                # job poll loop
│     │  ├─ pipeline.py            # parse→normalize→fx→categorize→dedup→reconcile
│     │  ├─ adapters/
│     │  │  ├─ base.py             # Adapter protocol
│     │  │  ├─ amex_xlsx.py        # your real format
│     │  │  ├─ generic_csv.py
│     │  │  └─ pdf_table.py        # pdfplumber/camelot (Phase 0 deterministic)
│     │  ├─ fx.py                  # rate stamping (CAD base)
│     │  ├─ categorize.py          # rules engine (AI tail is Phase 1)
│     │  ├─ reconcile.py
│     │  └─ llm/                   # provider gateway (scaffolded, idle in P0)
│     │     ├─ provider.py         # LLMProvider protocol
│     │     └─ anthropic.py
│     └─ tests/
│        ├─ fixtures/              # sanitized non-sensitive fixtures only
│        └─ test_pipeline.py       # golden regression: closing == 2855.59
└─ db/
   └─ migrations/                 # SQL migrations (sqitch/dbmate/atlas)
```

**Why this layout:** `shared-types` is the single source of truth for the
transaction shape and the query DSL, consumed by the TS app directly and mirrored
into Python via generated Pydantic models — so the two runtimes can't drift.

---

## 2. Infrastructure (docker-compose, self-hosted)

Four services, one command:

| Service | Image / build | Role |
|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | ledger + pgvector (embeddings unused until Phase 1) |
| `minio` | `minio/minio` | S3-compatible object store for raw statement files, encrypted |
| `worker` | build `services/worker` | Python ingestion/analytics; polls the job table |
| `web` | build `apps/web` | SvelteKit app + API routes (adapter-node) |

- **Object storage via MinIO** keeps the self-host path pure — no cloud dependency, but the same S3 API you'd use on R2/S3 later. Swappable by env. Raw files are encrypted before upload with the application envelope defined in [ADR-0001](decisions/0001-application-layer-statement-encryption.md).
- **No Redis in Phase 0.** The job queue is a Postgres table the worker polls (see §4). Add a real broker only if throughput demands it.
- Secrets via `.env` → compose env; `.env.example` documents every key. Provider API keys and the object-store key live here, never in the repo.

---

## 3. Canonical schema (Phase 0 subset)

Enough of §4 of the architecture doc to run the slice. Migrations in `db/migrations`.

```sql
create extension if not exists vector;

create table institution (
  id uuid primary key default gen_random_uuid(),
  name text not null
);

create table account (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid references institution(id),
  display_name text not null,
  kind text not null check (kind in ('credit_card','chequing','savings','wallet')),
  native_currency text not null,          -- 'CAD' for the Amex card
  account_ref_masked text                 -- '••••71001'; never store full number
);

create table statement (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references account(id),
  period_start date not null,
  period_end date not null,
  opening_balance numeric(14,2),
  closing_balance numeric(14,2),
  currency text not null,
  source_file_key text,                   -- MinIO object key
  reconcile_status text default 'pending' -- ok | gap | mismatch | pending
);

create table category (
  id uuid primary key default gen_random_uuid(),
  parent_id uuid references category(id),
  name text not null,
  kind text not null check (kind in ('spend','income','transfer','fee'))
);

create table merchant (
  id uuid primary key default gen_random_uuid(),
  canonical_name text not null,
  normalized_key text unique not null,
  embedding vector(1024)                  -- null in Phase 0
);

create table txn (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references account(id),
  statement_id uuid references statement(id),
  booked_date date not null,
  posted_date date,
  description_raw text not null,
  merchant_id uuid references merchant(id),
  category_id uuid references category(id),
  amount_native numeric(14,2) not null,   -- signed: +charge / -credit (card convention)
  currency_native text not null,
  amount_base numeric(14,2) not null,     -- = amount_native when native==base (Amex)
  currency_base text not null default 'CAD',
  fx_rate numeric(18,8) not null default 1,
  fx_rate_date date,
  external_ref text,                      -- Amex Reference id
  dedup_hash text unique not null,
  direction text not null,               -- debit|credit|payment|fee|refund|interest
  enrichment jsonb default '{}'::jsonb    -- foreign_spend {amount,currency}, flags
);
create index on txn (account_id, booked_date);
create index on txn (category_id);

-- Postgres-backed job queue (§4)
create table job (
  id uuid primary key default gen_random_uuid(),
  kind text not null,                    -- 'ingest'
  payload jsonb not null,                -- { file_keys: [...], account_id }
  status text not null default 'queued', -- queued|claimed|done|failed
  claimed_at timestamptz,
  finished_at timestamptz,
  result jsonb,
  error text,
  created_at timestamptz default now()
);

-- adapters (learned mappings live here from Phase 1; seeded for known formats now)
create table adapter (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid references institution(id),
  format text not null,                  -- pdf|csv|xlsx|ofx
  column_map jsonb,
  detection_fingerprint jsonb,
  version int not null default 1
);
```

---

## 4. Ingestion worker (Python)

**Job loop (`main.py`):** claim a `queued` job with
`update ... set status='claimed' where id = (select id from job where status='queued'
order by created_at for update skip locked limit 1) returning *` — safe
single-worker-or-many claiming, no Redis.

**Adapter protocol (`adapters/base.py`):**
```python
class Adapter(Protocol):
    format: str
    def detect(self, file: ParsedFile) -> float: ...      # 0..1 confidence
    def parse(self, file: ParsedFile) -> ParseResult: ...  # rows + statement meta
```
- `amex_xlsx.py` — knows the two-sheet export: `Transaction Details` carries the
  title period, booked/processed dates, description, amount, foreign spend,
  merchant, and reference; `Transaction Summary` carries opening and closing
  balances. Equivalent Description/Merchant text is accepted; conflicting
  aliases fail closed. Sign convention = charges positive.
- `generic_csv.py` — header auto-locate + best-effort field guess (deterministic;
  the AI mapper that handles the truly unknown is Phase 1).
- `pdf_table.py` — `pdfplumber` first, `camelot` for bordered tables. Extracts
  rows deterministically; if extraction yields nothing usable it marks the job
  `needs_ai` (the Phase 1 fallback hook — stubbed now).

**Pipeline (`pipeline.py`) per file:**
1. Load raw from MinIO → choose adapter by highest `detect()` score.
2. `parse()` → canonical rows + statement meta (Polars frame).
3. **FX stamp (`fx.py`):** if `currency_native == 'CAD'` → `amount_base =
   amount_native`, `fx_rate = 1` (the Amex case — no external call). Else fetch/
   cache the rate at `booked_date`. TZS coverage caveat noted in the architecture
   doc; Phase 0 never hits it.
4. **Categorize (`categorize.py`):** rules/dictionary only (port the keyword map
   from the PoC). Unknowns → `category = Other`, flagged for the Phase 1 AI tail.
5. **Dedup:** compute `dedup_hash`; `insert ... on conflict (dedup_hash) do nothing`.
6. **Reconcile (`reconcile.py`):** assert `opening + Σ amount_native == closing`
   per statement → set `reconcile_status`. Detect coverage gaps across statements.
7. Write result to `job.result` (`{added, skipped, reconcile}`) → status `done`.

---

## 5. LLM provider gateway (scaffold now, use in Phase 1)

Built in Phase 0 so decision 6 is structural, not bolted on later. Idle until
the AI passes exist.

```python
# services/worker/worker/llm/provider.py
class LLMProvider(Protocol):
    def complete(self, *, system: str, messages: list[Msg],
                 schema: dict | None = None, model_tier: Literal['cheap','capable']) -> dict: ...

# anthropic.py maps model_tier → concrete model ids; reads key from env.
# Selection is config-driven: LLM_PROVIDER=anthropic (future: others).
```
Mirror the same interface in the TS ask-service later. Every AI call in the whole
system goes through this one seam → swapping providers is a config + one adapter,
never a refactor.

---

## 6. API / BFF (SvelteKit server routes)

| Route | Does |
|---|---|
| `POST /api/ingest` | store files in MinIO, insert `ingest` job, return job id |
| `GET /api/jobs/:id` | job status + reconciliation report |
| `GET /api/accounts` | accounts, native currency, current balance |
| `GET /api/transactions` | filter/search/paginate (params = the query DSL subset) |
| `GET /api/analytics/:view` | `cashflow` and `balance` in Phase 0 |

The transaction filter params and the (future) NL query spec are the **same
DSL** — the executor in `lib/db.ts` turns a validated spec into parameterized
SQL. Building it here means the Phase 3 ask-layer plugs into an executor that
already exists.

---

## 7. Frontend (SvelteKit PWA)

Port the parts of the chat PoC that earned their place, restyled to the ledger
look:
- **Upload + job status** (drag-drop → poll `/api/jobs/:id` → toast on done).
- **Accounts strip** with current balances.
- **Running balance chart** — uPlot (fast on mobile).
- **Cash-flow chart** — ECharts (in vs out vs net by statement).
- **Transactions table** — search, category filter, amount/date sorting,
  processed-date end-of-day position, direct page selection, and configurable
  10/25/50/100-row pages.
- **PWA manifest + service worker** caching last aggregates for offline read.

Deliberately *not* in Phase 0: subscriptions view, anomalies, the ask-bar — those
ride on Phase 1/2/3 analytics.

---

## 8. Tests & CI (the correctness gate)

- **Golden reconciliation** (`test_pipeline.py` plus `scripts/phase0_smoke.py`):
  ingest three sanitized generated Amex fixtures, assert per-statement
  `reconcile_status='ok'` and consolidated
  **closing balance == 2855.59**, and that category/merchant totals match a
  checked-in snapshot. This runs in CI on every commit — **financial math never
  regresses silently.**
- **Idempotency test:** ingest the same file twice → second run adds 0 rows.
- **Adapter unit tests:** header-row location, sign convention, foreign-spend parsing.
- CI pipeline: typecheck (TS) + `ruff`/`mypy` (Py) + the test suite, gate on green.

---

## 9. Sequenced task list

**Milestone A — skeleton up (day-scale)**
- [x] Monorepo + `docker-compose` (postgres, minio, web, worker) boots
- [x] Migrations run; `shared-types` package created
- [x] `Makefile`: `up`, `migrate`, `seed`, `test`

**Milestone B — ingest a validated file end to end**
- [x] MinIO upload + `job` insert from `POST /api/ingest`
- [x] Worker poll loop claims jobs
- [x] `amex_xlsx` adapter + normalize + FX no-op stamp + dedup + reconcile
- [x] Sanitized golden test green (closing 2855.59)

**Milestone C — see it**
- [x] `/api/accounts`, `/api/transactions`, `/api/analytics/{balance,cashflow}`
- [x] Dashboard: balance chart (uPlot), cash-flow (ECharts), txn table
- [x] Upload UI + job-status polling + PWA install

**Milestone D — broaden ingestion (still Phase 0)**
- [x] `generic_csv` adapter + tests
- [x] `pdf_table` deterministic adapter + tests; `needs_ai` hook stubbed
- [x] `LLMProvider` gateway scaffolded (idle)

→ **Phase 1 starts here:** AI column-mapper for unknown formats, AI PDF fallback,
categorization AI tail, first foreign-*native* account to light up the FX path,
base-currency switch. All plug into seams built in Phase 0.

---

## 10. Phase 0 handoff

Automated acceptance is wired into CI and can be reproduced with `make smoke`
against a healthy fresh stack. Local acceptance with the owner's three original
Amex exports confirmed 193 canonical rows, three reconciled statements, the
same `2855.59` closing balance, and an idempotent repeat import. Before closing
Phase 0, review the Phase 1 statement inventory and create its backlog; no
provider key is needed while Phase 0 remains active.
