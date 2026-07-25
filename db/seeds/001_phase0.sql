BEGIN;

INSERT INTO institution (id, name)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    'American Express'
)
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    updated_at = now();

INSERT INTO account (
    id,
    institution_id,
    display_name,
    kind,
    native_currency,
    market_code,
    account_ref_masked
)
VALUES (
    '00000000-0000-4000-8000-000000000101',
    '00000000-0000-4000-8000-000000000001',
    'Amex Card',
    'credit_card',
    'CAD',
    'CA',
    NULL
)
ON CONFLICT (id) DO UPDATE
SET institution_id = EXCLUDED.institution_id,
    display_name = EXCLUDED.display_name,
    kind = EXCLUDED.kind,
    native_currency = EXCLUDED.native_currency,
    market_code = EXCLUDED.market_code,
    updated_at = now();

INSERT INTO ledger_settings (singleton, base_currency)
VALUES (true, 'CAD')
ON CONFLICT (singleton) DO NOTHING;

INSERT INTO category (id, parent_id, name, kind)
VALUES
    ('00000000-0000-4000-8000-00000000c001', NULL, 'Other', 'spend'),
    ('00000000-0000-4000-8000-00000000c002', NULL, 'Groceries', 'spend'),
    ('00000000-0000-4000-8000-00000000c003', NULL, 'Dining', 'spend'),
    ('00000000-0000-4000-8000-00000000c004', NULL, 'Transport', 'spend'),
    ('00000000-0000-4000-8000-00000000c005', NULL, 'Travel', 'spend'),
    ('00000000-0000-4000-8000-00000000c006', NULL, 'Shopping', 'spend'),
    ('00000000-0000-4000-8000-00000000c007', NULL, 'Entertainment', 'spend'),
    ('00000000-0000-4000-8000-00000000c008', NULL, 'Health', 'spend'),
    ('00000000-0000-4000-8000-00000000c009', NULL, 'Utilities', 'spend'),
    ('00000000-0000-4000-8000-00000000c00a', NULL, 'Fees', 'fee'),
    ('00000000-0000-4000-8000-00000000c00b', NULL, 'Income', 'income'),
    ('00000000-0000-4000-8000-00000000c00c', NULL, 'Transfers', 'transfer'),
    ('00000000-0000-4000-8000-00000000c00d', NULL, 'Payments', 'transfer'),
    ('00000000-0000-4000-8000-00000000c00e', NULL, 'Refunds', 'transfer'),
    ('00000000-0000-4000-8000-00000000c00f', NULL, 'Fees & Interest', 'fee')
ON CONFLICT (id) DO UPDATE
SET parent_id = EXCLUDED.parent_id,
    name = EXCLUDED.name,
    kind = EXCLUDED.kind,
    updated_at = now();

UPDATE category
SET is_protected = true,
    updated_at = now()
WHERE id = '00000000-0000-4000-8000-00000000c001';

INSERT INTO adapter (
    id,
    institution_id,
    format,
    column_map,
    detection_fingerprint,
    version
)
VALUES
    (
        '00000000-0000-4000-8000-00000000a001',
        '00000000-0000-4000-8000-000000000001',
        'xlsx',
        '{"Date":"booked_date","Date Processed":"posted_date","Description":"description_raw","Amount":"amount_native","Foreign Spend Amount":"foreign_spend","Reference":"external_ref"}'::jsonb,
        '{"required_headers":["Date","Description","Amount"],"optional_headers":["Date Processed","Foreign Spend Amount","Reference"],"header_scan_rows":20}'::jsonb,
        1
    ),
    (
        '00000000-0000-4000-8000-00000000a002',
        NULL,
        'csv',
        NULL,
        '{"required_field_groups":[["date","booked date","transaction date"],["amount","debit","credit"],["description","merchant","details"]],"header_scan_rows":20}'::jsonb,
        1
    )
ON CONFLICT (id) DO UPDATE
SET institution_id = EXCLUDED.institution_id,
    format = EXCLUDED.format,
    column_map = EXCLUDED.column_map,
    detection_fingerprint = EXCLUDED.detection_fingerprint,
    version = EXCLUDED.version,
    updated_at = now();

INSERT INTO fx_rate (base, quote, as_of, rate, source)
VALUES ('CAD', 'CAD', DATE '1970-01-01', 1, 'identity')
ON CONFLICT (base, quote, as_of) DO UPDATE
SET rate = EXCLUDED.rate,
    source = EXCLUDED.source,
    fetched_at = now();

COMMIT;
