-- migrate:up
CREATE UNIQUE INDEX txn_ofx_fitid_identity_idx
    ON txn (account_id, external_ref)
    WHERE external_ref IS NOT NULL
      AND enrichment ? 'ofx_transaction_type';

-- migrate:down
DROP INDEX IF EXISTS txn_ofx_fitid_identity_idx;
