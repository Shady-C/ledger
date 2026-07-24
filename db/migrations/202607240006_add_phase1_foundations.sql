-- migrate:up
ALTER TABLE account
    ADD COLUMN credit_limit numeric(14, 2),
    ADD CONSTRAINT account_credit_limit_positive
        CHECK (credit_limit IS NULL OR credit_limit > 0),
    ADD CONSTRAINT account_credit_limit_card_only
        CHECK (credit_limit IS NULL OR kind = 'credit_card');

CREATE OR REPLACE FUNCTION prevent_account_financial_identity_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF (NEW.kind, NEW.native_currency) IS DISTINCT FROM (OLD.kind, OLD.native_currency)
       AND (
           EXISTS (SELECT 1 FROM statement WHERE account_id = OLD.id)
           OR EXISTS (SELECT 1 FROM txn WHERE account_id = OLD.id)
       )
    THEN
        RAISE EXCEPTION 'account kind and native currency are immutable after financial data exists'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER account_financial_identity_immutable
BEFORE UPDATE OF kind, native_currency ON account
FOR EACH ROW
EXECUTE FUNCTION prevent_account_financial_identity_change();

CREATE TABLE ledger_settings (
    singleton boolean PRIMARY KEY DEFAULT true,
    base_currency text NOT NULL DEFAULT 'CAD',
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ledger_settings_singleton CHECK (singleton),
    CONSTRAINT ledger_settings_base_currency_iso CHECK (
        base_currency ~ '^[A-Z]{3}$'
    )
);

INSERT INTO ledger_settings (singleton, base_currency)
VALUES (true, 'CAD')
ON CONFLICT (singleton) DO NOTHING;

ALTER TABLE category
    ADD COLUMN archived_at timestamptz,
    ADD COLUMN is_protected boolean NOT NULL DEFAULT false;

UPDATE category
SET is_protected = true,
    updated_at = now()
WHERE parent_id IS NULL AND lower(name) = 'other';

CREATE OR REPLACE FUNCTION prevent_protected_category_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.is_protected
       AND (
           NEW.name IS DISTINCT FROM OLD.name
           OR NEW.kind IS DISTINCT FROM OLD.kind
           OR NEW.parent_id IS DISTINCT FROM OLD.parent_id
           OR NEW.archived_at IS DISTINCT FROM OLD.archived_at
           OR NOT NEW.is_protected
       )
    THEN
        RAISE EXCEPTION 'protected categories cannot be renamed, moved, archived, or unprotected'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER category_protected_immutable
BEFORE UPDATE ON category
FOR EACH ROW
EXECUTE FUNCTION prevent_protected_category_mutation();

ALTER TABLE txn
    ADD COLUMN category_source text NOT NULL DEFAULT 'fallback',
    ADD COLUMN category_confidence numeric(5, 4),
    ADD CONSTRAINT txn_category_source_valid CHECK (
        category_source IN (
            'fallback',
            'rule',
            'ai',
            'user_merchant',
            'user_transaction'
        )
    ),
    ADD CONSTRAINT txn_category_confidence_valid CHECK (
        category_confidence IS NULL
        OR (category_confidence >= 0 AND category_confidence <= 1)
    );

UPDATE txn
SET category_source = CASE
        WHEN category_id = '00000000-0000-4000-8000-00000000c001'::uuid
            THEN 'fallback'
        ELSE 'rule'
    END,
    category_confidence = CASE
        WHEN category_id IS NULL THEN NULL
        WHEN category_id = '00000000-0000-4000-8000-00000000c001'::uuid THEN 0
        ELSE 1
    END,
    updated_at = now();

CREATE TABLE merchant_category_mapping (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id uuid NOT NULL REFERENCES merchant (id) ON DELETE CASCADE,
    flow_type text NOT NULL,
    category_id uuid NOT NULL REFERENCES category (id) ON DELETE RESTRICT,
    source text NOT NULL,
    confidence numeric(5, 4),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT merchant_category_mapping_flow_valid CHECK (
        flow_type IN ('spend', 'income', 'transfer', 'refund', 'fee')
    ),
    CONSTRAINT merchant_category_mapping_source_valid CHECK (
        source IN ('ai', 'user_merchant')
    ),
    CONSTRAINT merchant_category_mapping_confidence_valid CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    CONSTRAINT merchant_category_mapping_unique UNIQUE (merchant_id, flow_type)
);

CREATE INDEX merchant_category_mapping_category_idx
    ON merchant_category_mapping (category_id);

CREATE TABLE categorization_proposal (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    opaque_key uuid NOT NULL DEFAULT gen_random_uuid(),
    merchant_id uuid NOT NULL REFERENCES merchant (id) ON DELETE CASCADE,
    flow_type text NOT NULL,
    proposed_category_id uuid REFERENCES category (id) ON DELETE RESTRICT,
    proposed_category_name text,
    proposed_category_kind text,
    confidence numeric(5, 4) NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    provider text NOT NULL,
    model text NOT NULL,
    raw_assignment jsonb NOT NULL DEFAULT '{}'::jsonb,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT categorization_proposal_opaque_key_unique UNIQUE (opaque_key),
    CONSTRAINT categorization_proposal_flow_valid CHECK (
        flow_type IN ('spend', 'income', 'transfer', 'refund', 'fee')
    ),
    CONSTRAINT categorization_proposal_target_valid CHECK (
        (
            proposed_category_id IS NOT NULL
            AND proposed_category_name IS NULL
            AND proposed_category_kind IS NULL
        ) OR (
            proposed_category_id IS NULL
            AND proposed_category_name IS NOT NULL
            AND btrim(proposed_category_name) <> ''
            AND proposed_category_kind IS NOT NULL
        )
    ),
    CONSTRAINT categorization_proposal_kind_valid CHECK (
        proposed_category_kind IS NULL
        OR proposed_category_kind IN ('spend', 'income', 'transfer', 'fee')
    ),
    CONSTRAINT categorization_proposal_confidence_valid CHECK (
        confidence >= 0 AND confidence <= 1
    ),
    CONSTRAINT categorization_proposal_status_valid CHECK (
        status IN ('pending', 'accepted', 'rejected')
    ),
    CONSTRAINT categorization_proposal_provider_not_blank CHECK (btrim(provider) <> ''),
    CONSTRAINT categorization_proposal_model_not_blank CHECK (btrim(model) <> ''),
    CONSTRAINT categorization_proposal_raw_assignment_object CHECK (
        jsonb_typeof(raw_assignment) = 'object'
    ),
    CONSTRAINT categorization_proposal_review_valid CHECK (
        (status = 'pending' AND reviewed_at IS NULL)
        OR (status <> 'pending' AND reviewed_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX categorization_proposal_pending_merchant_flow_idx
    ON categorization_proposal (merchant_id, flow_type)
    WHERE status = 'pending';

CREATE INDEX categorization_proposal_review_idx
    ON categorization_proposal (status, created_at, id);

ALTER TABLE job
    ADD COLUMN deduplication_key text,
    ADD COLUMN retry_count integer NOT NULL DEFAULT 0,
    ADD COLUMN max_retries integer NOT NULL DEFAULT 3,
    ADD CONSTRAINT job_kind_valid CHECK (
        kind IN ('ingest', 'categorize', 'fx_refresh', 'base_currency_rebuild')
    ),
    ADD CONSTRAINT job_deduplication_key_not_blank CHECK (
        deduplication_key IS NULL OR btrim(deduplication_key) <> ''
    ),
    ADD CONSTRAINT job_retry_count_valid CHECK (retry_count >= 0),
    ADD CONSTRAINT job_max_retries_valid CHECK (max_retries = 3),
    ADD CONSTRAINT job_retry_bound_valid CHECK (retry_count <= max_retries);

CREATE UNIQUE INDEX job_active_deduplication_idx
    ON job (kind, deduplication_key)
    WHERE deduplication_key IS NOT NULL
      AND status IN ('queued', 'claimed');

CREATE INDEX job_kind_status_created_at_idx
    ON job (kind, status, created_at DESC, id);

-- migrate:down
DROP INDEX IF EXISTS job_kind_status_created_at_idx;
DROP INDEX IF EXISTS job_active_deduplication_idx;

ALTER TABLE job
    DROP CONSTRAINT IF EXISTS job_retry_bound_valid,
    DROP CONSTRAINT IF EXISTS job_max_retries_valid,
    DROP CONSTRAINT IF EXISTS job_retry_count_valid,
    DROP CONSTRAINT IF EXISTS job_deduplication_key_not_blank,
    DROP CONSTRAINT IF EXISTS job_kind_valid,
    DROP COLUMN IF EXISTS max_retries,
    DROP COLUMN IF EXISTS retry_count,
    DROP COLUMN IF EXISTS deduplication_key;

DROP TABLE IF EXISTS categorization_proposal;
DROP TABLE IF EXISTS merchant_category_mapping;

ALTER TABLE txn
    DROP CONSTRAINT IF EXISTS txn_category_confidence_valid,
    DROP CONSTRAINT IF EXISTS txn_category_source_valid,
    DROP COLUMN IF EXISTS category_confidence,
    DROP COLUMN IF EXISTS category_source;

DROP TRIGGER IF EXISTS category_protected_immutable ON category;
DROP FUNCTION IF EXISTS prevent_protected_category_mutation();

ALTER TABLE category
    DROP COLUMN IF EXISTS is_protected,
    DROP COLUMN IF EXISTS archived_at;

DROP TABLE IF EXISTS ledger_settings;

DROP TRIGGER IF EXISTS account_financial_identity_immutable ON account;
DROP FUNCTION IF EXISTS prevent_account_financial_identity_change();

ALTER TABLE account
    DROP CONSTRAINT IF EXISTS account_credit_limit_card_only,
    DROP CONSTRAINT IF EXISTS account_credit_limit_positive,
    DROP COLUMN IF EXISTS credit_limit;
