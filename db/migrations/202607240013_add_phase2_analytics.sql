-- migrate:up
ALTER TABLE job
    DROP CONSTRAINT job_kind_valid,
    ADD CONSTRAINT job_kind_valid CHECK (
        kind IN (
            'ingest',
            'categorize',
            'fx_refresh',
            'base_currency_rebuild',
            'analytics_refresh'
        )
    );

CREATE TABLE analytics_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    generation bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    mode text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    source_watermark timestamptz,
    result jsonb,
    error text,
    requested_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CONSTRAINT analytics_run_mode_valid CHECK (mode IN ('full', 'incremental')),
    CONSTRAINT analytics_run_status_valid CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed')
    ),
    CONSTRAINT analytics_run_result_object CHECK (
        result IS NULL OR jsonb_typeof(result) = 'object'
    ),
    CONSTRAINT analytics_run_started_at_valid CHECK (
        status = 'queued' OR started_at IS NOT NULL
    ),
    CONSTRAINT analytics_run_finished_at_valid CHECK (
        status NOT IN ('succeeded', 'failed') OR finished_at IS NOT NULL
    ),
    CONSTRAINT analytics_run_error_valid CHECK (
        (status = 'failed' AND error IS NOT NULL AND btrim(error) <> '')
        OR (status <> 'failed' AND error IS NULL)
    )
);

CREATE INDEX analytics_run_status_requested_idx
    ON analytics_run (status, requested_at DESC, id);

CREATE TABLE analytics_settings (
    singleton boolean PRIMARY KEY DEFAULT true,
    sensitivity text NOT NULL DEFAULT 'balanced',
    published_generation bigint REFERENCES analytics_run (generation) ON DELETE RESTRICT,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT analytics_settings_singleton CHECK (singleton),
    CONSTRAINT analytics_settings_sensitivity_valid CHECK (
        sensitivity IN ('low', 'balanced', 'high')
    )
);

INSERT INTO analytics_settings (singleton, sensitivity)
VALUES (true, 'balanced')
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE analytics_monthly_aggregate (
    generation bigint NOT NULL REFERENCES analytics_run (generation) ON DELETE CASCADE,
    period_start date NOT NULL,
    dimension_type text NOT NULL,
    account_id uuid REFERENCES account (id) ON DELETE CASCADE,
    category_id uuid REFERENCES category (id) ON DELETE CASCADE,
    merchant_id uuid REFERENCES merchant (id) ON DELETE CASCADE,
    currency_base text NOT NULL DEFAULT 'CAD',
    inflow_base numeric(18, 2) NOT NULL DEFAULT 0,
    outflow_base numeric(18, 2) NOT NULL DEFAULT 0,
    spending_base numeric(18, 2) NOT NULL DEFAULT 0,
    net_base numeric(18, 2) NOT NULL DEFAULT 0,
    transaction_count integer NOT NULL DEFAULT 0,
    valued_count integer NOT NULL DEFAULT 0,
    pending_fx_count integer NOT NULL DEFAULT 0,
    pending_fx_by_currency jsonb NOT NULL DEFAULT '{}'::jsonb,
    coverage_status text NOT NULL DEFAULT 'complete',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT analytics_monthly_period_valid CHECK (
        EXTRACT(DAY FROM period_start) = 1
    ),
    CONSTRAINT analytics_monthly_dimension_type_valid CHECK (
        dimension_type IN ('ledger', 'account', 'category', 'merchant')
    ),
    CONSTRAINT analytics_monthly_dimension_valid CHECK (
        (dimension_type = 'ledger'
            AND account_id IS NULL AND category_id IS NULL AND merchant_id IS NULL)
        OR (dimension_type = 'account'
            AND account_id IS NOT NULL AND category_id IS NULL AND merchant_id IS NULL)
        OR (dimension_type = 'category'
            AND account_id IS NULL AND category_id IS NOT NULL AND merchant_id IS NULL)
        OR (dimension_type = 'merchant'
            AND account_id IS NULL AND category_id IS NULL AND merchant_id IS NOT NULL)
    ),
    CONSTRAINT analytics_monthly_currency_fixed CHECK (currency_base = 'CAD'),
    CONSTRAINT analytics_monthly_counts_valid CHECK (
        transaction_count >= 0
        AND valued_count >= 0
        AND pending_fx_count >= 0
        AND valued_count + pending_fx_count = transaction_count
    ),
    CONSTRAINT analytics_monthly_pending_fx_object CHECK (
        jsonb_typeof(pending_fx_by_currency) = 'object'
    ),
    CONSTRAINT analytics_monthly_coverage_valid CHECK (
        (coverage_status = 'complete' AND pending_fx_count = 0)
        OR (coverage_status = 'partial' AND pending_fx_count > 0)
    ),
    CONSTRAINT analytics_monthly_aggregate_unique
        UNIQUE NULLS NOT DISTINCT (
            generation,
            period_start,
            dimension_type,
            account_id,
            category_id,
            merchant_id
        )
);

CREATE INDEX analytics_monthly_period_dimension_idx
    ON analytics_monthly_aggregate (period_start DESC, dimension_type);

CREATE VIEW analytics_monthly_current AS
SELECT aggregate.*
FROM analytics_monthly_aggregate aggregate
JOIN analytics_settings settings
    ON settings.singleton
   AND settings.published_generation = aggregate.generation;

CREATE TABLE recurring_series (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    detector_fingerprint text NOT NULL UNIQUE,
    merchant_id uuid REFERENCES merchant (id) ON DELETE SET NULL,
    merchant_key text NOT NULL,
    flow_type text NOT NULL,
    status text NOT NULL DEFAULT 'detected',
    detected_cadence text NOT NULL,
    cadence_override text,
    comparison_basis text NOT NULL,
    comparison_currency text NOT NULL,
    detected_expected_amount numeric(18, 2) NOT NULL,
    expected_amount_override numeric(18, 2),
    detected_next_date date NOT NULL,
    next_date_override date,
    confidence numeric(5, 4) NOT NULL,
    first_occurrence_date date NOT NULL,
    latest_occurrence_date date NOT NULL,
    last_detected_generation bigint NOT NULL
        REFERENCES analytics_run (generation) ON DELETE RESTRICT,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT recurring_series_fingerprint_not_blank CHECK (
        btrim(detector_fingerprint) <> ''
    ),
    CONSTRAINT recurring_series_merchant_key_not_blank CHECK (btrim(merchant_key) <> ''),
    CONSTRAINT recurring_series_flow_valid CHECK (flow_type IN ('spend', 'income')),
    CONSTRAINT recurring_series_status_valid CHECK (
        status IN ('detected', 'confirmed', 'cancelled', 'ignored')
    ),
    CONSTRAINT recurring_series_detected_cadence_valid CHECK (
        detected_cadence IN ('weekly', 'biweekly', 'monthly', 'quarterly', 'annual')
    ),
    CONSTRAINT recurring_series_cadence_override_valid CHECK (
        cadence_override IS NULL
        OR cadence_override IN ('weekly', 'biweekly', 'monthly', 'quarterly', 'annual')
    ),
    CONSTRAINT recurring_series_basis_valid CHECK (
        comparison_basis IN ('original', 'native', 'base')
    ),
    CONSTRAINT recurring_series_currency_iso CHECK (
        comparison_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT recurring_series_amounts_positive CHECK (
        detected_expected_amount > 0
        AND (expected_amount_override IS NULL OR expected_amount_override > 0)
    ),
    CONSTRAINT recurring_series_confidence_valid CHECK (
        confidence >= 0 AND confidence <= 1
    ),
    CONSTRAINT recurring_series_dates_valid CHECK (
        latest_occurrence_date >= first_occurrence_date
        AND detected_next_date > latest_occurrence_date
    ),
    CONSTRAINT recurring_series_review_valid CHECK (
        status = 'detected' OR reviewed_at IS NOT NULL
    )
);

CREATE INDEX recurring_series_status_next_date_idx
    ON recurring_series (status, detected_next_date, id);

CREATE INDEX recurring_series_generation_idx
    ON recurring_series (last_detected_generation);

CREATE TABLE recurring_occurrence (
    series_id uuid NOT NULL REFERENCES recurring_series (id) ON DELETE CASCADE,
    transaction_id uuid NOT NULL REFERENCES txn (id) ON DELETE CASCADE,
    occurrence_number integer NOT NULL,
    occurrence_date date NOT NULL,
    comparison_amount numeric(18, 2) NOT NULL,
    comparison_currency text NOT NULL,
    comparison_basis text NOT NULL,
    match_source text NOT NULL DEFAULT 'detected',
    detected_generation bigint NOT NULL
        REFERENCES analytics_run (generation) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (series_id, transaction_id),
    CONSTRAINT recurring_occurrence_transaction_unique UNIQUE (transaction_id),
    CONSTRAINT recurring_occurrence_number_unique UNIQUE (series_id, occurrence_number),
    CONSTRAINT recurring_occurrence_number_positive CHECK (occurrence_number > 0),
    CONSTRAINT recurring_occurrence_amount_positive CHECK (comparison_amount > 0),
    CONSTRAINT recurring_occurrence_currency_iso CHECK (
        comparison_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT recurring_occurrence_basis_valid CHECK (
        comparison_basis IN ('original', 'native', 'base')
    ),
    CONSTRAINT recurring_occurrence_match_source_valid CHECK (
        match_source IN ('detected', 'user')
    )
);

CREATE INDEX recurring_occurrence_series_date_idx
    ON recurring_occurrence (series_id, occurrence_date, transaction_id);

CREATE TABLE insight_finding (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    detector_fingerprint text NOT NULL UNIQUE,
    finding_type text NOT NULL,
    severity text NOT NULL,
    status text NOT NULL DEFAULT 'new',
    headline text NOT NULL,
    evidence jsonb NOT NULL,
    account_id uuid REFERENCES account (id) ON DELETE SET NULL,
    transaction_id uuid REFERENCES txn (id) ON DELETE SET NULL,
    recurring_series_id uuid REFERENCES recurring_series (id) ON DELETE SET NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    last_detected_generation bigint NOT NULL
        REFERENCES analytics_run (generation) ON DELETE RESTRICT,
    reviewed_at timestamptz,
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT insight_finding_fingerprint_not_blank CHECK (
        btrim(detector_fingerprint) <> ''
    ),
    CONSTRAINT insight_finding_type_valid CHECK (
        finding_type IN (
            'unusual_amount',
            'unusual_frequency',
            'monthly_spike',
            'near_duplicate',
            'recurring_price_increase',
            'recurring_overdue',
            'reconciliation_mismatch',
            'coverage_gap',
            'pending_fx'
        )
    ),
    CONSTRAINT insight_finding_severity_valid CHECK (
        severity IN ('info', 'warning', 'critical')
    ),
    CONSTRAINT insight_finding_status_valid CHECK (
        status IN ('new', 'confirmed', 'dismissed', 'resolved')
    ),
    CONSTRAINT insight_finding_headline_not_blank CHECK (btrim(headline) <> ''),
    CONSTRAINT insight_finding_evidence_object CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT insight_finding_seen_dates_valid CHECK (last_seen_at >= first_seen_at),
    CONSTRAINT insight_finding_review_valid CHECK (
        status NOT IN ('confirmed', 'dismissed') OR reviewed_at IS NOT NULL
    ),
    CONSTRAINT insight_finding_resolution_valid CHECK (
        (status = 'resolved' AND resolved_at IS NOT NULL)
        OR (status <> 'resolved' AND resolved_at IS NULL)
    )
);

CREATE INDEX insight_finding_review_idx
    ON insight_finding (status, severity, last_seen_at DESC, id);

CREATE INDEX insight_finding_type_idx
    ON insight_finding (finding_type, last_seen_at DESC, id);

CREATE OR REPLACE FUNCTION publish_analytics_generation(
    target_run_id uuid,
    run_result jsonb DEFAULT '{}'::jsonb
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    target_generation bigint;
BEGIN
    IF jsonb_typeof(run_result) <> 'object' THEN
        RAISE EXCEPTION 'analytics run result must be a JSON object'
            USING ERRCODE = '23514';
    END IF;

    SELECT generation
    INTO target_generation
    FROM analytics_run
    WHERE id = target_run_id
      AND status IN ('queued', 'running')
    FOR UPDATE;

    IF target_generation IS NULL THEN
        RAISE EXCEPTION 'analytics run is missing or cannot be published'
            USING ERRCODE = '23514';
    END IF;

    UPDATE analytics_run
    SET status = 'succeeded',
        started_at = COALESCE(started_at, now()),
        finished_at = now(),
        result = run_result,
        error = NULL
    WHERE id = target_run_id;

    UPDATE analytics_settings
    SET published_generation = target_generation,
        updated_at = now()
    WHERE singleton;

    RETURN target_generation;
END;
$$;

INSERT INTO job (kind, payload, status, deduplication_key)
SELECT
    'analytics_refresh',
    '{"mode":"full"}'::jsonb,
    'queued',
    'analytics-refresh:ledger'
WHERE EXISTS (SELECT 1 FROM txn)
ON CONFLICT DO NOTHING;

-- migrate:down
DROP FUNCTION IF EXISTS publish_analytics_generation(uuid, jsonb);
DROP TABLE IF EXISTS insight_finding;
DROP TABLE IF EXISTS recurring_occurrence;
DROP TABLE IF EXISTS recurring_series;
DROP VIEW IF EXISTS analytics_monthly_current;
DROP TABLE IF EXISTS analytics_monthly_aggregate;
DROP TABLE IF EXISTS analytics_settings;
DROP TABLE IF EXISTS analytics_run;

DELETE FROM job WHERE kind = 'analytics_refresh';

ALTER TABLE job
    DROP CONSTRAINT job_kind_valid,
    ADD CONSTRAINT job_kind_valid CHECK (
        kind IN ('ingest', 'categorize', 'fx_refresh', 'base_currency_rebuild')
    );
