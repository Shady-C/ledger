-- migrate:up
UPDATE txn
SET category_confidence = 0,
    updated_at = now()
WHERE category_source = 'fallback'
  AND category_confidence IS DISTINCT FROM 0;

-- migrate:down
UPDATE txn
SET category_confidence = NULL,
    updated_at = now()
WHERE category_source = 'fallback'
  AND category_confidence = 0;
