# Ledger worker

The Phase 2 worker polls PostgreSQL for discriminated service jobs, downloads
raw statement objects from MinIO/S3, authenticates and decrypts their
`LEDGER01` AES-256-GCM envelopes, selects a deterministic or validated learned
adapter, normalizes three-layer transaction money, enriches available CAD
valuation, categorizes, deduplicates, reconciles native balances, and persists
the result. Separate jobs refresh FX and atomically materialize deterministic
analytics.

```sh
python -m pip install -e '.[dev]'
pytest
ruff check .
mypy
ledger-worker
```

`STATEMENT_ENCRYPTION_KEY` is required and must contain exactly 64 hexadecimal
characters. `WORKER_JOB_TIMEOUT_SECONDS` controls stale-claim recovery; active
jobs renew their fenced claim lease while processing.

The worker container installs Tesseract for the versioned
`im_bank_tz_pdf_v1` adapter. Direct host execution of that adapter needs a local
`tesseract` executable. The adapter is limited to the supplied stable I&M Bank
Tanzania TZS image layout and validates OCR evidence against running balances,
printed totals, and the closing balance. It never sends PDF content to a model
or external OCR service. From the repository root, run
`make im-bank-tz-acceptance` to validate local sanitized PDFs under
`output/pdf`; complete PDFs remain ignored local inputs.

Set `LEDGER_TEST_DATABASE_URL` to a migrated disposable PostgreSQL database to
include the opt-in persistence-level golden reconciliation test.

LLM providers are limited to validated redacted tabular mappings and minimized
categorization proposals. No financial arithmetic, OCR, reconciliation,
analytics, or finding detection is delegated to a model.
