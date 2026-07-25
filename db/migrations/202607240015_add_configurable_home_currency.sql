-- migrate:up
CREATE TABLE analytics_threshold_profile (
    base_currency text PRIMARY KEY,
    policy_version text NOT NULL,
    minimum_difference_low numeric(18, 2) NOT NULL,
    minimum_difference_balanced numeric(18, 2) NOT NULL,
    minimum_difference_high numeric(18, 2) NOT NULL,
    minimum_price_increase numeric(18, 2) NOT NULL,
    source_currency text,
    source_rate numeric(20, 8),
    source_rate_date date,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT analytics_threshold_profile_currency_supported CHECK (
        base_currency IN ('CAD', 'TZS')
    ),
    CONSTRAINT analytics_threshold_profile_policy_not_blank CHECK (
        btrim(policy_version) <> ''
    ),
    CONSTRAINT analytics_threshold_profile_values_positive CHECK (
        minimum_difference_low > 0
        AND minimum_difference_balanced > 0
        AND minimum_difference_high > 0
        AND minimum_price_increase > 0
    ),
    CONSTRAINT analytics_threshold_profile_sensitivity_order CHECK (
        minimum_difference_low >= minimum_difference_balanced
        AND minimum_difference_balanced >= minimum_difference_high
    ),
    CONSTRAINT analytics_threshold_profile_source_shape CHECK (
        (
            base_currency = 'CAD'
            AND source_currency IS NULL
            AND source_rate IS NULL
            AND source_rate_date IS NULL
        )
        OR (
            base_currency = 'TZS'
            AND source_currency = 'CAD'
            AND source_rate IS NOT NULL
            AND source_rate > 0
            AND source_rate_date IS NOT NULL
            AND source_rate_date BETWEEN
                (created_at AT TIME ZONE 'UTC')::date - 7
                AND (created_at AT TIME ZONE 'UTC')::date
        )
    ),
    CONSTRAINT analytics_threshold_profile_currency_policy_unique
        UNIQUE (base_currency, policy_version)
);

CREATE FUNCTION prevent_analytics_threshold_profile_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'analytics threshold profiles are frozen; create a migration for a new policy'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER analytics_threshold_profile_frozen
BEFORE UPDATE OR DELETE ON analytics_threshold_profile
FOR EACH ROW
EXECUTE FUNCTION prevent_analytics_threshold_profile_mutation();

INSERT INTO analytics_threshold_profile (
    base_currency,
    policy_version,
    minimum_difference_low,
    minimum_difference_balanced,
    minimum_difference_high,
    minimum_price_increase
) VALUES (
    'CAD',
    'materiality-v1',
    25.00,
    10.00,
    5.00,
    1.00
);

-- Upgrade any Stage 1 recurring rows created before policy-aware recurring
-- identities were introduced. The row itself is transformed so reviewed
-- status, cadence, date overrides, and user-entered amount overrides survive.
UPDATE recurring_series
SET detector_fingerprint = encode(
        sha256(convert_to(
            concat_ws(
                chr(31),
                market_scope,
                'recurring',
                merchant_key,
                flow_type,
                comparison_basis,
                'CAD',
                'materiality-v1'
            ),
            'UTF8'
        )),
        'hex'
    ),
    updated_at = now()
WHERE comparison_basis = 'base';

-- Recurring-overdue findings are cadence evidence rather than reporting-value
-- findings. Keep their row and review state, but follow the transformed series
-- identity and refresh the contextual evidence attached to that identity.
UPDATE insight_finding AS finding
SET detector_fingerprint = encode(
        sha256(convert_to(
            concat_ws(
                chr(31),
                finding.market_scope,
                encode(
                    sha256(convert_to(
                        concat_ws(
                            chr(31),
                            'recurring_overdue',
                            series.detector_fingerprint,
                            finding.evidence ->> 'expectedNextDate'
                        ),
                        'UTF8'
                    )),
                    'hex'
                )
            ),
            'UTF8'
        )),
        'hex'
    ),
    evidence = jsonb_set(
        jsonb_set(
            finding.evidence,
            '{baseCurrency}',
            '"CAD"'::jsonb,
            true
        ),
        '{thresholdPolicyVersion}',
        '"materiality-v1"'::jsonb,
        true
    ),
    updated_at = now()
FROM recurring_series AS series
WHERE finding.recurring_series_id = series.id
  AND finding.finding_type = 'recurring_overdue'
  AND series.comparison_basis = 'base'
  AND NULLIF(finding.evidence ->> 'expectedNextDate', '') IS NOT NULL;

-- Every successful home-currency change retains the exact quote and policy
-- evidence used by the atomic rewrite. The copied values deliberately do not
-- reference fx_rate so later cache maintenance cannot alter historical audit
-- evidence.
CREATE TABLE home_currency_switch_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    previous_currency text NOT NULL,
    target_currency text NOT NULL,
    conversion_rate numeric(18, 8) NOT NULL,
    rate_source text NOT NULL,
    rate_source_date date NOT NULL,
    threshold_policy_version text NOT NULL,
    switched_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT home_currency_switch_currencies_supported CHECK (
        previous_currency IN ('CAD', 'TZS')
        AND target_currency IN ('CAD', 'TZS')
    ),
    CONSTRAINT home_currency_switch_changes_currency CHECK (
        previous_currency <> target_currency
    ),
    CONSTRAINT home_currency_switch_rate_positive CHECK (
        conversion_rate > 0
    ),
    CONSTRAINT home_currency_switch_source_not_blank CHECK (
        btrim(rate_source) <> ''
    ),
    CONSTRAINT home_currency_switch_policy_not_blank CHECK (
        btrim(threshold_policy_version) <> ''
    ),
    CONSTRAINT home_currency_switch_rate_date_current CHECK (
        rate_source_date BETWEEN
            (switched_at AT TIME ZONE 'UTC')::date - 7
            AND (switched_at AT TIME ZONE 'UTC')::date
    ),
    CONSTRAINT home_currency_switch_target_policy_fkey
        FOREIGN KEY (target_currency, threshold_policy_version)
        REFERENCES analytics_threshold_profile (base_currency, policy_version)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT
);

CREATE INDEX home_currency_switch_audit_time_idx
    ON home_currency_switch_audit (switched_at DESC, id);

CREATE FUNCTION prevent_home_currency_switch_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'home currency switch audit records are immutable'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER home_currency_switch_audit_immutable
BEFORE UPDATE OR DELETE ON home_currency_switch_audit
FOR EACH ROW
EXECUTE FUNCTION prevent_home_currency_switch_audit_mutation();

ALTER TABLE analytics_run
    ADD COLUMN base_currency text,
    ADD COLUMN threshold_policy_version text;

UPDATE analytics_run
SET base_currency = 'CAD',
    threshold_policy_version = 'materiality-v1';

ALTER TABLE analytics_run
    ALTER COLUMN base_currency SET NOT NULL,
    ALTER COLUMN threshold_policy_version SET NOT NULL,
    ADD CONSTRAINT analytics_run_currency_supported CHECK (
        base_currency IN ('CAD', 'TZS')
    ),
    ADD CONSTRAINT analytics_run_threshold_policy_not_blank CHECK (
        btrim(threshold_policy_version) <> ''
    ),
    ADD CONSTRAINT analytics_run_threshold_profile_fkey
        FOREIGN KEY (base_currency, threshold_policy_version)
        REFERENCES analytics_threshold_profile (base_currency, policy_version)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    ADD CONSTRAINT analytics_run_generation_base_currency_unique
        UNIQUE (generation, base_currency);

CREATE INDEX analytics_run_currency_status_requested_idx
    ON analytics_run (base_currency, status, requested_at DESC, id);

ALTER TABLE analytics_monthly_aggregate
    DROP CONSTRAINT analytics_monthly_aggregate_generation_fkey,
    DROP CONSTRAINT analytics_monthly_currency_fixed,
    ALTER COLUMN currency_base DROP DEFAULT,
    ADD CONSTRAINT analytics_monthly_currency_supported CHECK (
        currency_base IN ('CAD', 'TZS')
    ),
    ADD CONSTRAINT analytics_monthly_generation_currency_fkey
        FOREIGN KEY (generation, currency_base)
        REFERENCES analytics_run (generation, base_currency)
        ON UPDATE RESTRICT
        ON DELETE CASCADE;

CREATE INDEX analytics_monthly_scope_currency_period_idx
    ON analytics_monthly_aggregate (
        market_scope,
        currency_base,
        period_start DESC,
        dimension_type
    );

ALTER TABLE ledger_settings
    DROP CONSTRAINT ledger_settings_phase2_cad_only,
    ALTER COLUMN base_currency DROP DEFAULT,
    ADD CONSTRAINT ledger_settings_base_currency_supported CHECK (
        base_currency IN ('CAD', 'TZS')
    );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM analytics_settings AS settings
        JOIN analytics_run AS published
          ON published.generation = settings.published_generation
        JOIN ledger_settings AS ledger ON ledger.singleton
        WHERE settings.singleton
          AND (
              published.status <> 'succeeded'
              OR published.base_currency <> ledger.base_currency
          )
    ) THEN
        RAISE EXCEPTION
            'existing analytics publication is not safe for currency fencing'
            USING ERRCODE = '23514';
    END IF;
END
$$;

ALTER TABLE txn
    DROP CONSTRAINT txn_valuation_complete,
    DROP CONSTRAINT txn_phase2_cad_base,
    ALTER COLUMN currency_base DROP DEFAULT,
    ADD CONSTRAINT txn_reporting_currency_supported CHECK (
        currency_base IN ('CAD', 'TZS')
    ),
    ADD CONSTRAINT txn_valuation_complete CHECK (
        (
            currency_native = currency_base
            AND amount_base = amount_native
            AND fx_rate = 1
            AND fx_rate_date IS NOT NULL
        )
        OR (
            currency_native <> currency_base
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

-- New and rewritten reporting rows must use the ledger's active home currency.
-- Currency switches update ledger_settings first, rewrite every transaction in
-- the same transaction, and are validated as a complete unit at commit.
CREATE FUNCTION enforce_transaction_reporting_currency()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    configured_currency text;
BEGIN
    SELECT base_currency
    INTO configured_currency
    FROM ledger_settings
    WHERE singleton;

    IF configured_currency IS NULL THEN
        RAISE EXCEPTION 'ledger settings singleton is missing'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.currency_base <> configured_currency THEN
        RAISE EXCEPTION
            'transaction reporting currency must match the active home currency'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER transaction_reporting_currency_matches_settings
BEFORE INSERT OR UPDATE OF currency_base ON txn
FOR EACH ROW
EXECUTE FUNCTION enforce_transaction_reporting_currency();

CREATE FUNCTION check_ledger_reporting_currency_consistency()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM analytics_threshold_profile
        WHERE base_currency = NEW.base_currency
    ) THEN
        RAISE EXCEPTION
            'home currency requires a frozen analytics threshold profile'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM txn
        WHERE currency_base <> NEW.base_currency
    ) THEN
        RAISE EXCEPTION
            'all transaction reporting values must match the active home currency'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ledger_settings_reporting_currency_consistent
AFTER UPDATE OF base_currency ON ledger_settings
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION check_ledger_reporting_currency_consistency();

CREATE FUNCTION unpublish_incompatible_analytics_generation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.base_currency IS DISTINCT FROM OLD.base_currency THEN
        UPDATE analytics_settings AS settings
        SET published_generation = NULL,
            updated_at = now()
        FROM analytics_run AS published
        WHERE settings.singleton
          AND settings.published_generation = published.generation
          AND published.base_currency <> NEW.base_currency;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER ledger_currency_change_unpublishes_analytics
AFTER UPDATE OF base_currency ON ledger_settings
FOR EACH ROW
EXECUTE FUNCTION unpublish_incompatible_analytics_generation();

CREATE FUNCTION enforce_analytics_publication_currency()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    run_currency text;
    run_status text;
    configured_currency text;
BEGIN
    IF NEW.published_generation IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT base_currency, status
    INTO run_currency, run_status
    FROM analytics_run
    WHERE generation = NEW.published_generation;

    SELECT base_currency
    INTO configured_currency
    FROM ledger_settings
    WHERE singleton;

    IF run_currency IS NULL OR configured_currency IS NULL THEN
        RAISE EXCEPTION 'analytics publication dependencies are missing'
            USING ERRCODE = '23514';
    END IF;
    IF run_status <> 'succeeded' THEN
        RAISE EXCEPTION 'only a succeeded analytics generation can be published'
            USING ERRCODE = '23514';
    END IF;
    IF run_currency <> configured_currency THEN
        RAISE EXCEPTION
            'analytics generation currency must match the active home currency'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER analytics_publication_currency_guard
BEFORE INSERT OR UPDATE OF published_generation ON analytics_settings
FOR EACH ROW
EXECUTE FUNCTION enforce_analytics_publication_currency();

CREATE OR REPLACE FUNCTION publish_analytics_generation(
    target_run_id uuid,
    run_result jsonb DEFAULT '{}'::jsonb
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    target_generation bigint;
    target_currency text;
    configured_currency text;
BEGIN
    IF jsonb_typeof(run_result) <> 'object' THEN
        RAISE EXCEPTION 'analytics run result must be a JSON object'
            USING ERRCODE = '23514';
    END IF;

    SELECT generation, base_currency
    INTO target_generation, target_currency
    FROM analytics_run
    WHERE id = target_run_id
      AND status IN ('queued', 'running')
    FOR UPDATE;

    IF target_generation IS NULL THEN
        RAISE EXCEPTION 'analytics run is missing or cannot be published'
            USING ERRCODE = '23514';
    END IF;

    SELECT base_currency
    INTO configured_currency
    FROM ledger_settings
    WHERE singleton
    FOR SHARE;

    IF configured_currency IS NULL OR target_currency <> configured_currency THEN
        RAISE EXCEPTION
            'analytics generation currency must match the active home currency'
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

-- migrate:down
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ledger_settings
        WHERE base_currency <> 'CAD'
    ) THEN
        RAISE EXCEPTION
            'cannot roll back configurable home currency while TZS is active'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM txn WHERE currency_base <> 'CAD')
       OR EXISTS (
           SELECT 1 FROM analytics_run WHERE base_currency <> 'CAD'
       )
       OR EXISTS (
           SELECT 1
           FROM analytics_monthly_aggregate
           WHERE currency_base <> 'CAD'
       )
       OR EXISTS (
           SELECT 1
           FROM recurring_series
           WHERE comparison_basis = 'base'
             AND comparison_currency <> 'CAD'
       )
       OR EXISTS (
           SELECT 1
           FROM recurring_occurrence
           WHERE comparison_basis = 'base'
             AND comparison_currency <> 'CAD'
       )
    THEN
        RAISE EXCEPTION
            'cannot roll back configurable home currency while non-CAD reporting history exists'
            USING ERRCODE = '23514';
    END IF;
END
$$;

DROP FUNCTION IF EXISTS publish_analytics_generation(uuid, jsonb);

DROP TRIGGER IF EXISTS analytics_publication_currency_guard ON analytics_settings;
DROP FUNCTION IF EXISTS enforce_analytics_publication_currency();
DROP TRIGGER IF EXISTS ledger_currency_change_unpublishes_analytics ON ledger_settings;
DROP FUNCTION IF EXISTS unpublish_incompatible_analytics_generation();
DROP TRIGGER IF EXISTS ledger_settings_reporting_currency_consistent ON ledger_settings;
DROP FUNCTION IF EXISTS check_ledger_reporting_currency_consistency();
DROP TRIGGER IF EXISTS transaction_reporting_currency_matches_settings ON txn;
DROP FUNCTION IF EXISTS enforce_transaction_reporting_currency();

DROP INDEX IF EXISTS analytics_monthly_scope_currency_period_idx;

ALTER TABLE analytics_monthly_aggregate
    DROP CONSTRAINT IF EXISTS analytics_monthly_generation_currency_fkey,
    DROP CONSTRAINT IF EXISTS analytics_monthly_currency_supported,
    ALTER COLUMN currency_base SET DEFAULT 'CAD',
    ADD CONSTRAINT analytics_monthly_aggregate_generation_fkey
        FOREIGN KEY (generation)
        REFERENCES analytics_run (generation)
        ON DELETE CASCADE,
    ADD CONSTRAINT analytics_monthly_currency_fixed CHECK (currency_base = 'CAD');

DROP INDEX IF EXISTS analytics_run_currency_status_requested_idx;

ALTER TABLE analytics_run
    DROP CONSTRAINT IF EXISTS analytics_run_generation_base_currency_unique,
    DROP CONSTRAINT IF EXISTS analytics_run_threshold_profile_fkey,
    DROP CONSTRAINT IF EXISTS analytics_run_threshold_policy_not_blank,
    DROP CONSTRAINT IF EXISTS analytics_run_currency_supported,
    DROP COLUMN threshold_policy_version,
    DROP COLUMN base_currency;

ALTER TABLE txn
    DROP CONSTRAINT IF EXISTS txn_valuation_complete,
    DROP CONSTRAINT IF EXISTS txn_reporting_currency_supported,
    ALTER COLUMN currency_base SET DEFAULT 'CAD',
    ADD CONSTRAINT txn_phase2_cad_base CHECK (currency_base = 'CAD'),
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

ALTER TABLE ledger_settings
    DROP CONSTRAINT IF EXISTS ledger_settings_base_currency_supported,
    ALTER COLUMN base_currency SET DEFAULT 'CAD',
    ADD CONSTRAINT ledger_settings_phase2_cad_only CHECK (base_currency = 'CAD');

DROP TRIGGER IF EXISTS home_currency_switch_audit_immutable
    ON home_currency_switch_audit;
DROP FUNCTION IF EXISTS prevent_home_currency_switch_audit_mutation();
DROP INDEX IF EXISTS home_currency_switch_audit_time_idx;
DROP TABLE home_currency_switch_audit;

DROP TRIGGER IF EXISTS analytics_threshold_profile_frozen
    ON analytics_threshold_profile;
DROP FUNCTION IF EXISTS prevent_analytics_threshold_profile_mutation();
DROP TABLE analytics_threshold_profile;

CREATE FUNCTION publish_analytics_generation(
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
