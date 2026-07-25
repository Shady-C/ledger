-- migrate:up
ALTER TABLE account
    ADD COLUMN market_code text,
    ADD CONSTRAINT account_market_code_valid CHECK (
        market_code IS NULL OR market_code IN ('CA', 'TZ')
    );

CREATE INDEX account_market_code_idx
    ON account (market_code, id)
    WHERE market_code IS NOT NULL;

ALTER TABLE ledger_settings
    ADD COLUMN market_profile text,
    ADD CONSTRAINT ledger_settings_market_profile_valid CHECK (
        market_profile IS NULL OR market_profile IN ('CA', 'TZ')
    );

-- Existing accounts intentionally remain unassigned. The trigger makes market
-- membership mandatory only for accounts created after this migration.
CREATE FUNCTION require_new_account_market_code()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.market_code IS NULL THEN
        RAISE EXCEPTION 'new accounts require a market code'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER account_market_code_required_on_insert
BEFORE INSERT ON account
FOR EACH ROW
EXECUTE FUNCTION require_new_account_market_code();

-- Reassigning an account changes every scoped aggregate, recurring series, and
-- finding that can include its financial history. Promote any active analytics
-- job to a full rerun, or enqueue one when no refresh is active.
CREATE FUNCTION enqueue_account_market_analytics_refresh()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_job_id uuid;
    enqueue_attempt integer;
BEGIN
    IF OLD.market_code IS NOT DISTINCT FROM NEW.market_code
       OR NOT (
           EXISTS (SELECT 1 FROM statement WHERE account_id = NEW.id)
           OR EXISTS (SELECT 1 FROM txn WHERE account_id = NEW.id)
       )
    THEN
        RETURN NEW;
    END IF;

    -- The partial unique active-job index is the enqueue arbiter. A producer
    -- can finish between our first UPDATE snapshot and a conflicting INSERT,
    -- so retry that disappeared-conflict window instead of silently losing
    -- the required rebuild.
    FOR enqueue_attempt IN 1..5 LOOP
        UPDATE job
        SET payload = payload
                || '{"mode":"full","rerun_requested":true}'::jsonb,
            updated_at = now()
        WHERE kind = 'analytics_refresh'
          AND status IN ('queued', 'claimed');

        IF FOUND THEN
            RETURN NEW;
        END IF;

        inserted_job_id := NULL;
        INSERT INTO job (kind, payload, status, deduplication_key)
        VALUES (
            'analytics_refresh',
            '{"mode":"full"}'::jsonb,
            'queued',
            'analytics-refresh:ledger'
        )
        ON CONFLICT DO NOTHING
        RETURNING id INTO inserted_job_id;

        IF inserted_job_id IS NOT NULL THEN
            RETURN NEW;
        END IF;
    END LOOP;

    RAISE EXCEPTION
        'could not enqueue analytics refresh after concurrent job turnover'
        USING ERRCODE = '40001';

END;
$$;

CREATE TRIGGER account_market_change_refreshes_analytics
AFTER UPDATE OF market_code ON account
FOR EACH ROW
EXECUTE FUNCTION enqueue_account_market_analytics_refresh();

DROP VIEW analytics_monthly_current;

DROP INDEX analytics_monthly_period_dimension_idx;

ALTER TABLE analytics_monthly_aggregate
    DROP CONSTRAINT analytics_monthly_aggregate_unique,
    ADD COLUMN market_scope text NOT NULL DEFAULT 'ALL',
    ADD CONSTRAINT analytics_monthly_market_scope_valid CHECK (
        market_scope IN ('ALL', 'CA', 'TZ')
    ),
    ADD CONSTRAINT analytics_monthly_aggregate_unique
        UNIQUE NULLS NOT DISTINCT (
            generation,
            market_scope,
            period_start,
            dimension_type,
            account_id,
            category_id,
            merchant_id
        );

CREATE INDEX analytics_monthly_period_dimension_idx
    ON analytics_monthly_aggregate (
        market_scope,
        period_start DESC,
        dimension_type
    );

CREATE VIEW analytics_monthly_current AS
SELECT aggregate.*
FROM analytics_monthly_aggregate aggregate
JOIN analytics_settings settings
    ON settings.singleton
   AND settings.published_generation = aggregate.generation;

DROP INDEX recurring_series_status_next_date_idx;
DROP INDEX recurring_series_generation_idx;

ALTER TABLE recurring_series
    DROP CONSTRAINT recurring_series_detector_fingerprint_key,
    ADD COLUMN market_scope text NOT NULL DEFAULT 'ALL',
    ADD CONSTRAINT recurring_series_market_scope_valid CHECK (
        market_scope IN ('ALL', 'CA', 'TZ')
    ),
    ADD CONSTRAINT recurring_series_market_fingerprint_unique
        UNIQUE (market_scope, detector_fingerprint);

-- Phase 1 normally emitted only CAD comparison rows for the base basis, but
-- that semantic was not constrained on recurring_series. Fail closed if dirty
-- legacy currencies would collapse two reviewed rows onto one canonical
-- scope/currency/policy-aware identity.
DO $$
BEGIN
    IF EXISTS (
        SELECT target_fingerprint
        FROM (
            SELECT encode(
                    sha256(convert_to(
                        concat_ws(
                            chr(31),
                            'ALL',
                            'recurring',
                            merchant_key,
                            flow_type,
                            comparison_basis,
                            CASE
                                WHEN comparison_basis = 'base' THEN 'CAD'
                                ELSE comparison_currency
                            END,
                            CASE
                                WHEN comparison_basis = 'base'
                                    THEN 'materiality-v1'
                            END
                        ),
                        'UTF8'
                    )),
                    'hex'
                ) AS target_fingerprint
            FROM recurring_series
        ) AS candidate
        GROUP BY target_fingerprint
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'market-scope migration would collapse recurring review identities'
            USING ERRCODE = '23514';
    END IF;
END
$$;

-- Existing ALL series retain their row IDs and review overrides while adopting
-- the scope-bearing identity used by the worker. Reporting-valued series carry
-- the fixed Stage 1 currency and threshold policy; Phase 2.1 transforms those
-- two identity parts in place during a home-currency switch.
UPDATE recurring_series
SET detector_fingerprint = encode(
        sha256(convert_to(
            concat_ws(
                chr(31),
                'ALL',
                'recurring',
                merchant_key,
                flow_type,
                comparison_basis,
                CASE
                    WHEN comparison_basis = 'base' THEN 'CAD'
                    ELSE comparison_currency
                END,
                CASE
                    WHEN comparison_basis = 'base' THEN 'materiality-v1'
                END
            ),
            'UTF8'
        )),
        'hex'
    ),
    updated_at = now();

CREATE INDEX recurring_series_status_next_date_idx
    ON recurring_series (market_scope, status, detected_next_date, id);

CREATE INDEX recurring_series_generation_idx
    ON recurring_series (market_scope, last_detected_generation);

-- A transaction legitimately participates in its regional series and the ALL
-- series. The primary key still prevents duplicates within one series.
ALTER TABLE recurring_occurrence
    DROP CONSTRAINT recurring_occurrence_transaction_unique;

DROP INDEX insight_finding_review_idx;
DROP INDEX insight_finding_type_idx;

ALTER TABLE insight_finding
    DROP CONSTRAINT insight_finding_detector_fingerprint_key,
    ADD COLUMN market_scope text NOT NULL DEFAULT 'ALL',
    ADD CONSTRAINT insight_finding_market_scope_valid CHECK (
        market_scope IN ('ALL', 'CA', 'TZ')
    ),
    ADD CONSTRAINT insight_finding_market_fingerprint_unique
        UNIQUE (market_scope, detector_fingerprint);

-- Keep the pre-scope raw fingerprint only as rollback metadata. API mapping
-- removes this private key. Native/source identities wrap the old raw hash in
-- ALL; overdue identities also incorporate the newly scoped series hash.
UPDATE insight_finding
SET evidence = evidence || jsonb_build_object(
        '_migration014DetectorFingerprint', detector_fingerprint,
        'marketScope', 'ALL',
        'baseCurrency', 'CAD',
        'thresholdPolicyVersion', 'materiality-v1'
    );

UPDATE insight_finding
SET detector_fingerprint = encode(
        sha256(convert_to(
            concat_ws(chr(31), 'ALL', detector_fingerprint),
            'UTF8'
        )),
        'hex'
    ),
    updated_at = now()
WHERE finding_type IN (
    'unusual_frequency',
    'near_duplicate',
    'reconciliation_mismatch',
    'coverage_gap'
);

UPDATE insight_finding AS finding
SET detector_fingerprint = encode(
        sha256(convert_to(
            concat_ws(
                chr(31),
                'ALL',
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
    updated_at = now()
FROM recurring_series AS series
WHERE finding.finding_type = 'recurring_overdue'
  AND series.id = finding.recurring_series_id;

-- Reporting-valued findings must be regenerated under the active currency and
-- threshold policy. Resolve the legacy row and give it a non-conflicting,
-- scope/currency/policy-bearing archival identity.
UPDATE insight_finding
SET detector_fingerprint = encode(
        sha256(convert_to(
            concat_ws(
                chr(31),
                'ALL',
                'CAD',
                'materiality-v1',
                'legacy',
                detector_fingerprint
            ),
            'UTF8'
        )),
        'hex'
    ),
    status = 'resolved',
    resolved_at = COALESCE(resolved_at, now()),
    updated_at = now()
WHERE finding_type IN (
    'unusual_amount',
    'monthly_spike',
    'recurring_price_increase',
    'pending_fx'
);

CREATE INDEX insight_finding_review_idx
    ON insight_finding (
        market_scope,
        status,
        severity,
        last_seen_at DESC,
        id
    );

CREATE INDEX insight_finding_type_idx
    ON insight_finding (market_scope, finding_type, last_seen_at DESC, id);

-- migrate:down
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM account WHERE market_code IS NOT NULL)
       OR EXISTS (
           SELECT 1 FROM ledger_settings WHERE market_profile IS NOT NULL
       )
       OR EXISTS (
           SELECT 1 FROM analytics_monthly_aggregate WHERE market_scope <> 'ALL'
       )
       OR EXISTS (SELECT 1 FROM recurring_series WHERE market_scope <> 'ALL')
       OR EXISTS (SELECT 1 FROM insight_finding WHERE market_scope <> 'ALL')
       OR EXISTS (
           SELECT 1
           FROM insight_finding
           WHERE NOT (evidence ? '_migration014DetectorFingerprint')
       )
       OR EXISTS (
           SELECT 1
           FROM recurring_occurrence
           GROUP BY transaction_id
           HAVING count(*) > 1
       )
    THEN
        RAISE EXCEPTION
            'cannot roll back market scopes while market assignments or scoped analytics exist'
            USING ERRCODE = '23514';
    END IF;
END
$$;

DROP TRIGGER IF EXISTS account_market_change_refreshes_analytics ON account;
DROP FUNCTION IF EXISTS enqueue_account_market_analytics_refresh();
DROP TRIGGER IF EXISTS account_market_code_required_on_insert ON account;
DROP FUNCTION IF EXISTS require_new_account_market_code();

DROP INDEX IF EXISTS insight_finding_type_idx;
DROP INDEX IF EXISTS insight_finding_review_idx;

UPDATE insight_finding
SET detector_fingerprint = evidence ->> '_migration014DetectorFingerprint',
    evidence = evidence
        - '_migration014DetectorFingerprint'
        - 'marketScope'
        - 'baseCurrency'
        - 'thresholdPolicyVersion',
    updated_at = now();

ALTER TABLE insight_finding
    DROP CONSTRAINT IF EXISTS insight_finding_market_fingerprint_unique,
    DROP CONSTRAINT IF EXISTS insight_finding_market_scope_valid,
    ADD CONSTRAINT insight_finding_detector_fingerprint_key
        UNIQUE (detector_fingerprint),
    DROP COLUMN market_scope;

CREATE INDEX insight_finding_review_idx
    ON insight_finding (status, severity, last_seen_at DESC, id);

CREATE INDEX insight_finding_type_idx
    ON insight_finding (finding_type, last_seen_at DESC, id);

ALTER TABLE recurring_occurrence
    ADD CONSTRAINT recurring_occurrence_transaction_unique UNIQUE (transaction_id);

DROP INDEX IF EXISTS recurring_series_generation_idx;
DROP INDEX IF EXISTS recurring_series_status_next_date_idx;

UPDATE recurring_series
SET detector_fingerprint = encode(
        sha256(convert_to(
            concat_ws(
                chr(31),
                'recurring',
                merchant_key,
                flow_type,
                comparison_basis,
                comparison_currency
            ),
            'UTF8'
        )),
        'hex'
    ),
    updated_at = now();

ALTER TABLE recurring_series
    DROP CONSTRAINT IF EXISTS recurring_series_market_fingerprint_unique,
    DROP CONSTRAINT IF EXISTS recurring_series_market_scope_valid,
    ADD CONSTRAINT recurring_series_detector_fingerprint_key
        UNIQUE (detector_fingerprint),
    DROP COLUMN market_scope;

CREATE INDEX recurring_series_status_next_date_idx
    ON recurring_series (status, detected_next_date, id);

CREATE INDEX recurring_series_generation_idx
    ON recurring_series (last_detected_generation);

DROP VIEW IF EXISTS analytics_monthly_current;
DROP INDEX IF EXISTS analytics_monthly_period_dimension_idx;

ALTER TABLE analytics_monthly_aggregate
    DROP CONSTRAINT IF EXISTS analytics_monthly_aggregate_unique,
    DROP CONSTRAINT IF EXISTS analytics_monthly_market_scope_valid,
    ADD CONSTRAINT analytics_monthly_aggregate_unique
        UNIQUE NULLS NOT DISTINCT (
            generation,
            period_start,
            dimension_type,
            account_id,
            category_id,
            merchant_id
        ),
    DROP COLUMN market_scope;

CREATE INDEX analytics_monthly_period_dimension_idx
    ON analytics_monthly_aggregate (period_start DESC, dimension_type);

CREATE VIEW analytics_monthly_current AS
SELECT aggregate.*
FROM analytics_monthly_aggregate aggregate
JOIN analytics_settings settings
    ON settings.singleton
   AND settings.published_generation = aggregate.generation;

ALTER TABLE ledger_settings
    DROP CONSTRAINT IF EXISTS ledger_settings_market_profile_valid,
    DROP COLUMN market_profile;

DROP INDEX IF EXISTS account_market_code_idx;

ALTER TABLE account
    DROP CONSTRAINT IF EXISTS account_market_code_valid,
    DROP COLUMN market_code;
