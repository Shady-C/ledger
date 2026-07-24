-- migrate:up
CREATE TABLE job (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    claimed_at timestamptz,
    finished_at timestamptz,
    result jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT job_kind_not_blank CHECK (btrim(kind) <> ''),
    CONSTRAINT job_payload_is_object CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT job_status_valid CHECK (
        status IN ('queued', 'claimed', 'done', 'failed', 'needs_ai')
    ),
    CONSTRAINT job_result_is_object CHECK (
        result IS NULL OR jsonb_typeof(result) = 'object'
    ),
    CONSTRAINT job_claimed_at_valid CHECK (
        status = 'queued' OR claimed_at IS NOT NULL
    ),
    CONSTRAINT job_finished_at_valid CHECK (
        status NOT IN ('done', 'failed', 'needs_ai') OR finished_at IS NOT NULL
    )
);

CREATE INDEX job_queue_claim_idx
    ON job (created_at, id)
    WHERE status = 'queued';

CREATE INDEX job_status_created_at_idx ON job (status, created_at DESC);

CREATE TABLE adapter (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id uuid REFERENCES institution (id) ON DELETE CASCADE,
    format text NOT NULL,
    column_map jsonb,
    detection_fingerprint jsonb,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT adapter_format_valid CHECK (
        format IN ('pdf', 'csv', 'xlsx', 'ofx')
    ),
    CONSTRAINT adapter_column_map_is_object CHECK (
        column_map IS NULL OR jsonb_typeof(column_map) = 'object'
    ),
    CONSTRAINT adapter_fingerprint_is_object CHECK (
        detection_fingerprint IS NULL
        OR jsonb_typeof(detection_fingerprint) = 'object'
    ),
    CONSTRAINT adapter_version_positive CHECK (version > 0),
    CONSTRAINT adapter_institution_format_version_unique
        UNIQUE NULLS NOT DISTINCT (institution_id, format, version)
);

CREATE INDEX adapter_institution_format_idx
    ON adapter (institution_id, format, version DESC);

CREATE TABLE fx_rate (
    base text NOT NULL,
    quote text NOT NULL,
    as_of date NOT NULL,
    rate numeric(18, 8) NOT NULL,
    source text NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (base, quote, as_of),
    CONSTRAINT fx_rate_base_iso CHECK (base ~ '^[A-Z]{3}$'),
    CONSTRAINT fx_rate_quote_iso CHECK (quote ~ '^[A-Z]{3}$'),
    CONSTRAINT fx_rate_positive CHECK (rate > 0),
    CONSTRAINT fx_rate_source_not_blank CHECK (btrim(source) <> ''),
    CONSTRAINT fx_rate_identity_is_one CHECK (
        base <> quote OR rate = 1
    )
);

CREATE INDEX fx_rate_lookup_idx
    ON fx_rate (base, quote, as_of DESC);

-- migrate:down
DROP TABLE IF EXISTS fx_rate;
DROP TABLE IF EXISTS adapter;
DROP TABLE IF EXISTS job;
