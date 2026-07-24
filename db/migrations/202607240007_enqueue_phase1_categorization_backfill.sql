-- migrate:up
INSERT INTO job (kind, payload, status, deduplication_key)
SELECT
    'categorize',
    '{"mode":"backfill"}'::jsonb,
    'queued',
    'phase1:auto-categorization-backfill:v1'
WHERE EXISTS (
    SELECT 1
    FROM txn
    JOIN merchant ON merchant.id = txn.merchant_id
    WHERE txn.category_source = 'fallback'
)
ON CONFLICT DO NOTHING;

-- migrate:down
DELETE FROM job
WHERE kind = 'categorize'
  AND deduplication_key = 'phase1:auto-categorization-backfill:v1';
