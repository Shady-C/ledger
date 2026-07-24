-- migrate:up
CREATE TABLE statement (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid NOT NULL REFERENCES account (id) ON DELETE RESTRICT,
    period_start date NOT NULL,
    period_end date NOT NULL,
    opening_balance numeric(14, 2),
    closing_balance numeric(14, 2),
    currency text NOT NULL,
    source_file_key text,
    reconcile_status text NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT statement_period_valid CHECK (period_end >= period_start),
    CONSTRAINT statement_currency_iso CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT statement_source_file_key_not_blank CHECK (
        source_file_key IS NULL OR btrim(source_file_key) <> ''
    ),
    CONSTRAINT statement_reconcile_status_valid CHECK (
        reconcile_status IN ('pending', 'ok', 'gap', 'mismatch')
    )
);

CREATE INDEX statement_account_period_idx
    ON statement (account_id, period_end DESC, period_start DESC);

CREATE TABLE txn (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid NOT NULL REFERENCES account (id) ON DELETE RESTRICT,
    statement_id uuid REFERENCES statement (id) ON DELETE SET NULL,
    booked_date date NOT NULL,
    posted_date date,
    description_raw text NOT NULL,
    merchant_id uuid REFERENCES merchant (id) ON DELETE SET NULL,
    category_id uuid REFERENCES category (id) ON DELETE SET NULL,
    amount_native numeric(14, 2) NOT NULL,
    currency_native text NOT NULL,
    amount_base numeric(14, 2) NOT NULL,
    currency_base text NOT NULL DEFAULT 'CAD',
    fx_rate numeric(18, 8) NOT NULL DEFAULT 1,
    fx_rate_date date,
    external_ref text,
    dedup_hash text NOT NULL,
    direction text NOT NULL,
    enrichment jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT txn_description_not_blank CHECK (btrim(description_raw) <> ''),
    CONSTRAINT txn_currency_native_iso CHECK (
        currency_native ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT txn_currency_base_iso CHECK (currency_base ~ '^[A-Z]{3}$'),
    CONSTRAINT txn_fx_rate_positive CHECK (fx_rate > 0),
    CONSTRAINT txn_dedup_hash_not_blank CHECK (btrim(dedup_hash) <> ''),
    CONSTRAINT txn_dedup_hash_unique UNIQUE (dedup_hash),
    CONSTRAINT txn_direction_valid CHECK (
        direction IN (
            'debit',
            'credit',
            'payment',
            'fee',
            'refund',
            'interest'
        )
    ),
    CONSTRAINT txn_enrichment_is_object CHECK (
        jsonb_typeof(enrichment) = 'object'
    )
);

CREATE INDEX txn_account_booked_date_idx
    ON txn (account_id, booked_date DESC, id);

CREATE INDEX txn_statement_idx ON txn (statement_id);

CREATE INDEX txn_category_booked_date_idx
    ON txn (category_id, booked_date DESC);

CREATE INDEX txn_merchant_booked_date_idx
    ON txn (merchant_id, booked_date DESC);

-- migrate:down
DROP TABLE IF EXISTS txn;
DROP TABLE IF EXISTS statement;
