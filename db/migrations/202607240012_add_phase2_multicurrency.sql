-- migrate:up
ALTER TABLE txn
    ALTER COLUMN amount_base DROP NOT NULL,
    ALTER COLUMN fx_rate DROP NOT NULL,
    ALTER COLUMN fx_rate DROP DEFAULT,
    ALTER COLUMN currency_base SET DEFAULT 'CAD',
    ADD COLUMN original_amount numeric(14, 2),
    ADD COLUMN original_currency text,
    ADD COLUMN fx_fee_amount_native numeric(14, 2),
    ADD COLUMN is_fx_fee boolean NOT NULL DEFAULT false;

UPDATE txn
SET original_amount = CASE
        WHEN amount_native < 0
        THEN -abs((enrichment #>> '{foreign_spend,amount}')::numeric)
        ELSE abs((enrichment #>> '{foreign_spend,amount}')::numeric)
    END,
    original_currency = upper(enrichment #>> '{foreign_spend,currency}'),
    enrichment = enrichment - 'foreign_spend',
    updated_at = now()
WHERE jsonb_typeof(enrichment -> 'foreign_spend') = 'object'
  AND (enrichment #>> '{foreign_spend,amount}') ~ '^-?[0-9]+([.][0-9]+)?$'
  AND upper(enrichment #>> '{foreign_spend,currency}') ~ '^[A-Z]{3}$';

WITH current_settings AS (
    SELECT base_currency
    FROM ledger_settings
    WHERE singleton
), valuation AS (
    SELECT
        transaction.id,
        rate.rate,
        rate.as_of,
        rate.source
    FROM txn AS transaction
    LEFT JOIN LATERAL (
        SELECT cached.rate, cached.as_of, cached.source
        FROM fx_rate AS cached
        WHERE cached.base = transaction.currency_native
          AND cached.quote = 'CAD'
          AND cached.as_of BETWEEN transaction.booked_date - 7
                               AND transaction.booked_date
        ORDER BY cached.as_of DESC
        LIMIT 1
    ) AS rate ON transaction.currency_native <> 'CAD'
)
UPDATE txn
SET currency_base = 'CAD',
    amount_base = CASE
        WHEN current_settings.base_currency = 'CAD' THEN txn.amount_base
        WHEN txn.currency_native = 'CAD' THEN txn.amount_native
        WHEN valuation.rate IS NOT NULL THEN round(txn.amount_native * valuation.rate, 2)
        ELSE NULL
    END,
    fx_rate = CASE
        WHEN current_settings.base_currency = 'CAD' THEN txn.fx_rate
        WHEN txn.currency_native = 'CAD' THEN 1
        ELSE valuation.rate
    END,
    fx_rate_date = CASE
        WHEN current_settings.base_currency = 'CAD' THEN txn.fx_rate_date
        WHEN txn.currency_native = 'CAD' THEN txn.booked_date
        ELSE valuation.as_of
    END,
    enrichment = CASE
        WHEN current_settings.base_currency = 'CAD' THEN txn.enrichment
        WHEN txn.currency_native = 'CAD'
        THEN jsonb_set(txn.enrichment, '{fx_source}', '"identity"'::jsonb, true)
        WHEN valuation.source IS NOT NULL
        THEN jsonb_set(txn.enrichment, '{fx_source}', to_jsonb(valuation.source), true)
        ELSE txn.enrichment - 'fx_source'
    END,
    updated_at = now()
FROM valuation, current_settings
WHERE txn.id = valuation.id;

UPDATE ledger_settings
SET base_currency = 'CAD', updated_at = now()
WHERE singleton;

ALTER TABLE ledger_settings
    ADD CONSTRAINT ledger_settings_phase2_cad_only CHECK (base_currency = 'CAD');

ALTER TABLE txn
    ADD CONSTRAINT txn_phase2_cad_base CHECK (currency_base = 'CAD'),
    ADD CONSTRAINT txn_original_pair_complete CHECK (
        (original_amount IS NULL AND original_currency IS NULL)
        OR (original_amount IS NOT NULL AND original_currency IS NOT NULL)
    ),
    ADD CONSTRAINT txn_original_currency_iso CHECK (
        original_currency IS NULL OR original_currency ~ '^[A-Z]{3}$'
    ),
    ADD CONSTRAINT txn_original_sign_matches_posted CHECK (
        original_amount IS NULL
        OR original_amount = 0
        OR amount_native = 0
        OR sign(original_amount) = sign(amount_native)
    ),
    ADD CONSTRAINT txn_fx_fee_nonnegative CHECK (
        fx_fee_amount_native IS NULL OR fx_fee_amount_native >= 0
    ),
    ADD CONSTRAINT txn_fx_fee_within_posted_amount CHECK (
        fx_fee_amount_native IS NULL OR fx_fee_amount_native <= abs(amount_native)
    ),
    ADD CONSTRAINT txn_fx_fee_shape CHECK (
        NOT is_fx_fee OR fx_fee_amount_native IS NULL
    ),
    ADD CONSTRAINT txn_standalone_fx_fee_direction CHECK (
        NOT is_fx_fee OR direction = 'fee'
    ),
    ADD CONSTRAINT txn_valuation_complete CHECK (
        (
            currency_native = 'CAD'
            AND amount_base = amount_native
            AND fx_rate = 1
            AND fx_rate_date IS NOT NULL
        )
        OR (
            currency_native <> 'CAD'
            AND (
                (amount_base IS NULL AND fx_rate IS NULL AND fx_rate_date IS NULL)
                OR (
                    amount_base IS NOT NULL
                    AND fx_rate IS NOT NULL
                    AND fx_rate_date IS NOT NULL
                    AND amount_base = round(amount_native * fx_rate, 2)
                    AND fx_rate_date BETWEEN booked_date - 7 AND booked_date
                )
            )
        )
    );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM statement
        JOIN account ON account.id = statement.account_id
        WHERE statement.currency <> account.native_currency
    ) THEN
        RAISE EXCEPTION 'existing statement currency differs from its account currency';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM txn
        JOIN account ON account.id = txn.account_id
        WHERE txn.currency_native <> account.native_currency
    ) THEN
        RAISE EXCEPTION 'existing transaction currency differs from its account currency';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM txn
        JOIN statement ON statement.id = txn.statement_id
        WHERE txn.account_id <> statement.account_id
           OR txn.currency_native <> statement.currency
    ) THEN
        RAISE EXCEPTION 'existing transaction conflicts with its statement account or currency';
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION enforce_statement_account_currency()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    account_currency text;
BEGIN
    SELECT native_currency
    INTO account_currency
    FROM account
    WHERE id = NEW.account_id;

    IF account_currency IS NOT NULL AND NEW.currency <> account_currency THEN
        RAISE EXCEPTION 'statement currency must match the selected account currency'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER statement_account_currency_matches
BEFORE INSERT OR UPDATE OF account_id, currency ON statement
FOR EACH ROW
EXECUTE FUNCTION enforce_statement_account_currency();

CREATE OR REPLACE FUNCTION enforce_transaction_account_currency()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    account_currency text;
    statement_account_id uuid;
    statement_currency text;
BEGIN
    SELECT native_currency
    INTO account_currency
    FROM account
    WHERE id = NEW.account_id;

    IF account_currency IS NOT NULL AND NEW.currency_native <> account_currency THEN
        RAISE EXCEPTION 'transaction posted currency must match the selected account currency'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.statement_id IS NOT NULL THEN
        SELECT account_id, currency
        INTO statement_account_id, statement_currency
        FROM statement
        WHERE id = NEW.statement_id;

        IF statement_account_id IS NOT NULL
           AND (
               statement_account_id <> NEW.account_id
               OR statement_currency <> NEW.currency_native
           )
        THEN
            RAISE EXCEPTION 'transaction account and currency must match its statement'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER transaction_account_currency_matches
BEFORE INSERT OR UPDATE OF account_id, statement_id, currency_native ON txn
FOR EACH ROW
EXECUTE FUNCTION enforce_transaction_account_currency();

-- A previously non-CAD reporting ledger can legitimately have transactions
-- that remain unvalued after the safe cached-rate migration. Keep retrying the
-- derived layer without blocking or changing native reconciliation truth.
INSERT INTO job (kind, payload, status, deduplication_key)
SELECT
    'fx_refresh',
    '{"target_base_currency":"CAD"}'::jsonb,
    'queued',
    'phase2:fx-refresh:CAD:backfill:v1'
WHERE EXISTS (
    SELECT 1
    FROM txn
    WHERE amount_base IS NULL
       OR (
           original_amount IS NOT NULL
           AND original_currency IS DISTINCT FROM currency_native
       )
)
ON CONFLICT DO NOTHING;

CREATE INDEX txn_pending_fx_idx
    ON txn (booked_date, currency_native)
    WHERE amount_base IS NULL;

-- Retire queued public requests that conflict with the fixed-CAD Phase 2 policy.
UPDATE job
SET status = 'failed',
    error = 'Phase 2 fixes the reporting currency to CAD',
    finished_at = now(),
    claim_token = NULL,
    updated_at = now()
WHERE kind = 'base_currency_rebuild'
  AND status IN ('queued', 'claimed')
  AND upper(payload ->> 'target_base_currency') <> 'CAD';

-- migrate:down
DROP INDEX IF EXISTS txn_pending_fx_idx;

DROP TRIGGER IF EXISTS transaction_account_currency_matches ON txn;
DROP FUNCTION IF EXISTS enforce_transaction_account_currency();
DROP TRIGGER IF EXISTS statement_account_currency_matches ON statement;
DROP FUNCTION IF EXISTS enforce_statement_account_currency();

DELETE FROM job
WHERE kind = 'fx_refresh'
  AND deduplication_key = 'phase2:fx-refresh:CAD:backfill:v1';

ALTER TABLE txn
    DROP CONSTRAINT IF EXISTS txn_valuation_complete,
    DROP CONSTRAINT IF EXISTS txn_standalone_fx_fee_direction,
    DROP CONSTRAINT IF EXISTS txn_fx_fee_shape,
    DROP CONSTRAINT IF EXISTS txn_fx_fee_within_posted_amount,
    DROP CONSTRAINT IF EXISTS txn_fx_fee_nonnegative,
    DROP CONSTRAINT IF EXISTS txn_original_sign_matches_posted,
    DROP CONSTRAINT IF EXISTS txn_original_currency_iso,
    DROP CONSTRAINT IF EXISTS txn_original_pair_complete,
    DROP CONSTRAINT IF EXISTS txn_phase2_cad_base;

ALTER TABLE ledger_settings
    DROP CONSTRAINT IF EXISTS ledger_settings_phase2_cad_only;

UPDATE txn
SET enrichment = jsonb_set(
        enrichment,
        '{foreign_spend}',
        jsonb_build_object(
            'amount', abs(original_amount)::text,
            'currency', original_currency
        ),
        true
    )
WHERE original_amount IS NOT NULL AND original_currency IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM txn WHERE amount_base IS NULL OR fx_rate IS NULL) THEN
        RAISE EXCEPTION 'cannot roll back Phase 2 while CAD valuations are pending';
    END IF;
END
$$;

ALTER TABLE txn
    DROP COLUMN is_fx_fee,
    DROP COLUMN fx_fee_amount_native,
    DROP COLUMN original_currency,
    DROP COLUMN original_amount,
    ALTER COLUMN amount_base SET NOT NULL,
    ALTER COLUMN fx_rate SET DEFAULT 1,
    ALTER COLUMN fx_rate SET NOT NULL;
