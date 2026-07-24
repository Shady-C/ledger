-- migrate:up
-- Keep the oldest statement row for each uploaded object, repoint its
-- transactions, and remove redundant statement rows before enforcing the
-- source-level idempotency guarantee. NULL source keys intentionally remain
-- unconstrained because PostgreSQL UNIQUE treats them as distinct.
WITH statement_keeper AS (
    SELECT DISTINCT ON (account_id, source_file_key)
        account_id,
        source_file_key,
        id AS keeper_id
    FROM statement
    WHERE source_file_key IS NOT NULL
    ORDER BY account_id, source_file_key, created_at, id
), statement_duplicate AS (
    SELECT
        duplicate.id AS duplicate_id,
        keeper.keeper_id
    FROM statement AS duplicate
    JOIN statement_keeper AS keeper
      ON keeper.account_id = duplicate.account_id
     AND keeper.source_file_key = duplicate.source_file_key
    WHERE duplicate.id <> keeper.keeper_id
)
UPDATE txn
SET statement_id = statement_duplicate.keeper_id,
    updated_at = now()
FROM statement_duplicate
WHERE txn.statement_id = statement_duplicate.duplicate_id;

WITH statement_keeper AS (
    SELECT DISTINCT ON (account_id, source_file_key)
        account_id,
        source_file_key,
        id AS keeper_id
    FROM statement
    WHERE source_file_key IS NOT NULL
    ORDER BY account_id, source_file_key, created_at, id
)
DELETE FROM statement AS duplicate
USING statement_keeper AS keeper
WHERE duplicate.account_id = keeper.account_id
  AND duplicate.source_file_key = keeper.source_file_key
  AND duplicate.id <> keeper.keeper_id;

ALTER TABLE statement
    ADD CONSTRAINT statement_account_source_file_unique
    UNIQUE (account_id, source_file_key);

ALTER TABLE job
    ADD COLUMN claim_token uuid;

CREATE UNIQUE INDEX job_claim_token_unique_idx
    ON job (claim_token)
    WHERE claim_token IS NOT NULL;

CREATE INDEX job_stale_claim_idx
    ON job (claimed_at, id)
    WHERE status = 'claimed';

-- migrate:down
DROP INDEX IF EXISTS job_stale_claim_idx;
DROP INDEX IF EXISTS job_claim_token_unique_idx;

ALTER TABLE job
    DROP COLUMN IF EXISTS claim_token;

ALTER TABLE statement
    DROP CONSTRAINT IF EXISTS statement_account_source_file_unique;
