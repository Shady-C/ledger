import { json } from '@sveltejs/kit';
import {
  categorizationProposalDecisionSchema,
  uuidSchema,
  type CategoryKind,
  type TransactionFlowType
} from '@ledger/shared-types';

import { apiError, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { getPool, transactionFlowSql } from '$lib/server/db.js';
import { postgresErrorCode } from '$lib/server/phase1.js';

type LockedProposal = {
  id: string;
  merchant_id: string;
  flow_type: TransactionFlowType;
  proposed_category_id: string | null;
  proposed_category_name: string | null;
  proposed_category_kind: CategoryKind | null;
  confidence: string;
  status: 'pending' | 'accepted' | 'rejected';
};

const expectedCategoryKind: Record<TransactionFlowType, CategoryKind> = {
  spend: 'spend',
  income: 'income',
  transfer: 'transfer',
  refund: 'transfer',
  fee: 'fee'
};

export async function PATCH({ params, request }) {
  const id = uuidSchema.safeParse(params.id);
  if (!id.success) return apiError(400, 'invalid_proposal', 'The proposal id is invalid.');
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON proposal decision.');
  }
  const parsed = categorizationProposalDecisionSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);

  const client = await getPool().connect();
  try {
    await client.query('BEGIN');
    const proposalResult = await client.query<LockedProposal>(
      `SELECT
         id::text,
         merchant_id::text,
         flow_type,
         proposed_category_id::text,
         proposed_category_name,
         proposed_category_kind,
         confidence::text,
         status
       FROM categorization_proposal
       WHERE id = $1::uuid
       FOR UPDATE`,
      [id.data]
    );
    const proposal = proposalResult.rows[0];
    if (!proposal) {
      await client.query('ROLLBACK');
      return apiError(404, 'proposal_not_found', 'That categorization proposal was not found.');
    }
    if (proposal.status !== 'pending') {
      await client.query('ROLLBACK');
      return apiError(409, 'proposal_already_reviewed', 'That proposal has already been reviewed.');
    }

    if (parsed.data.decision === 'reject') {
      await client.query(
        `UPDATE categorization_proposal
         SET status = 'rejected', reviewed_at = now(), updated_at = now()
         WHERE id = $1::uuid`,
        [id.data]
      );
      await client.query('COMMIT');
      return json(
        { proposalId: id.data, status: 'rejected', categoryId: null, transactionsUpdated: 0 },
        { headers: { 'cache-control': 'no-store' } }
      );
    }

    const requiredKind = expectedCategoryKind[proposal.flow_type];
    let categoryId = proposal.proposed_category_id;
    if (categoryId) {
      const category = await client.query<{ id: string; kind: CategoryKind }>(
        `SELECT id::text, kind
         FROM category
         WHERE id = $1::uuid AND archived_at IS NULL`,
        [categoryId]
      );
      if (!category.rows[0] || category.rows[0].kind !== requiredKind) {
        await client.query('ROLLBACK');
        return apiError(409, 'proposal_category_invalid', 'The proposed category is unavailable or incompatible.');
      }
    } else {
      if (!proposal.proposed_category_name || proposal.proposed_category_kind !== requiredKind) {
        await client.query('ROLLBACK');
        return apiError(409, 'proposal_category_invalid', 'The proposed new category is incompatible.');
      }
      const created = await client.query<{ id: string }>(
        `INSERT INTO category (name, kind)
         VALUES ($1, $2)
         RETURNING id::text`,
        [proposal.proposed_category_name, proposal.proposed_category_kind]
      );
      categoryId = created.rows[0]?.id ?? null;
      if (!categoryId) throw new Error('Accepted category proposal did not create a category');
    }

    const mapping = await client.query<{ id: string }>(
      `INSERT INTO merchant_category_mapping (
         merchant_id, flow_type, category_id, source, confidence
       ) VALUES ($1::uuid, $2, $3::uuid, 'ai', $4::numeric)
       ON CONFLICT (merchant_id, flow_type) DO UPDATE
       SET category_id = EXCLUDED.category_id,
           source = EXCLUDED.source,
           confidence = EXCLUDED.confidence,
           updated_at = now()
       WHERE merchant_category_mapping.source <> 'user_merchant'
       RETURNING id::text`,
      [proposal.merchant_id, proposal.flow_type, categoryId, proposal.confidence]
    );

    let transactionsUpdated = 0;
    if (mapping.rows[0]) {
      const flow = transactionFlowSql('transaction', 'account');
      const updated = await client.query(
        `UPDATE txn AS transaction
         SET category_id = $1::uuid,
             category_source = 'ai',
             category_confidence = $2::numeric,
             updated_at = now()
         FROM account
         WHERE account.id = transaction.account_id
           AND transaction.merchant_id = $3::uuid
           AND (${flow}) = $4
           AND transaction.category_source NOT IN ('user_transaction', 'user_merchant')`,
        [categoryId, proposal.confidence, proposal.merchant_id, proposal.flow_type]
      );
      transactionsUpdated = updated.rowCount ?? 0;
    }

    await client.query(
      `UPDATE categorization_proposal
       SET status = 'accepted',
           proposed_category_id = $2::uuid,
           proposed_category_name = NULL,
           proposed_category_kind = NULL,
           reviewed_at = now(),
           updated_at = now()
       WHERE id = $1::uuid`,
      [id.data, categoryId]
    );
    await client.query('COMMIT');
    return json(
      { proposalId: id.data, status: 'accepted', categoryId, transactionsUpdated },
      { headers: { 'cache-control': 'no-store' } }
    );
  } catch (error) {
    await client.query('ROLLBACK');
    if (postgresErrorCode(error) === '23505') {
      return apiError(409, 'category_exists', 'That proposed category already exists.');
    }
    return unavailableOrInternal(error, 'review categorization proposal');
  } finally {
    client.release();
  }
}
