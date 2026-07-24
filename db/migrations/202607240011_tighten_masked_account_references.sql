-- migrate:up
ALTER TABLE account
    DROP CONSTRAINT account_reference_is_masked,
    ADD CONSTRAINT account_reference_is_masked CHECK (
        account_ref_masked IS NULL
        OR (
            char_length(account_ref_masked) BETWEEN 4 AND 64
            AND account_ref_masked = btrim(account_ref_masked)
            AND account_ref_masked ~ '^[^0-9]+[0-9]{2,6}$'
        )
    );

-- migrate:down
ALTER TABLE account
    DROP CONSTRAINT account_reference_is_masked,
    ADD CONSTRAINT account_reference_is_masked CHECK (
        account_ref_masked IS NULL
        OR (
            char_length(account_ref_masked) BETWEEN 4 AND 64
            AND account_ref_masked !~ '[0-9]{7,}'
        )
    );
