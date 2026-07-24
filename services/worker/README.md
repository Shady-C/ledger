# Ledger worker

The Phase 0 worker polls PostgreSQL for ingestion jobs, downloads raw statement
objects from MinIO/S3, authenticates and decrypts their `LEDGER01` AES-256-GCM
envelopes, selects a deterministic adapter, normalizes and
categorizes transactions, stamps CAD at a 1:1 base-currency rate, deduplicates,
reconciles, and persists the result.

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

Set `LEDGER_TEST_DATABASE_URL` to a migrated disposable PostgreSQL database to
include the opt-in persistence-level golden reconciliation test.

The LLM provider package is an intentionally idle seam. No Phase 0 pipeline
path invokes it and no financial arithmetic is delegated to a model.
