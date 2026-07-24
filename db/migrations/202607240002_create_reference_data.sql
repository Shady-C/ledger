-- migrate:up
CREATE TABLE institution (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT institution_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT institution_name_unique UNIQUE (name)
);

CREATE TABLE account (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id uuid REFERENCES institution (id) ON DELETE RESTRICT,
    display_name text NOT NULL,
    kind text NOT NULL,
    native_currency text NOT NULL,
    account_ref_masked text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT account_display_name_not_blank CHECK (btrim(display_name) <> ''),
    CONSTRAINT account_kind_valid CHECK (
        kind IN ('credit_card', 'chequing', 'savings', 'wallet')
    ),
    CONSTRAINT account_native_currency_iso CHECK (
        native_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT account_reference_is_masked CHECK (
        account_ref_masked IS NULL
        OR (
            char_length(account_ref_masked) BETWEEN 4 AND 64
            AND account_ref_masked !~ '[0-9]{7,}'
        )
    )
);

CREATE INDEX account_institution_idx ON account (institution_id);

CREATE TABLE category (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id uuid REFERENCES category (id) ON DELETE RESTRICT,
    name text NOT NULL,
    kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT category_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT category_kind_valid CHECK (
        kind IN ('spend', 'income', 'transfer', 'fee')
    ),
    CONSTRAINT category_not_own_parent CHECK (parent_id IS DISTINCT FROM id)
);

CREATE UNIQUE INDEX category_root_name_unique_idx
    ON category (lower(name))
    WHERE parent_id IS NULL;

CREATE UNIQUE INDEX category_child_name_unique_idx
    ON category (parent_id, lower(name))
    WHERE parent_id IS NOT NULL;

CREATE TABLE merchant (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name text NOT NULL,
    normalized_key text NOT NULL,
    embedding vector(1024),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT merchant_canonical_name_not_blank CHECK (
        btrim(canonical_name) <> ''
    ),
    CONSTRAINT merchant_normalized_key_not_blank CHECK (
        btrim(normalized_key) <> ''
    ),
    CONSTRAINT merchant_normalized_key_unique UNIQUE (normalized_key)
);

-- migrate:down
DROP TABLE IF EXISTS merchant;
DROP TABLE IF EXISTS category;
DROP TABLE IF EXISTS account;
DROP TABLE IF EXISTS institution;
