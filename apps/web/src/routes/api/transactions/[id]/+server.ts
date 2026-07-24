import { json } from '@sveltejs/kit';
import {
  transactionCategoryPatchSchema,
  uuidSchema,
  type CategoryKind,
  type TransactionFlowType
} from '@ledger/shared-types';

import { apiError, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { getPool, transactionFlowSql } from '$lib/server/db.js';

type TransactionForCategory = {
  id: string;
  merchant_id: string | null;
  flow_type: TransactionFlowType;
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
  if (!id.success) return apiError(400, 'invalid_transaction', 'The transaction id is invalid.');
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON category correction.');
  }
  const parsed = transactionCategoryPatchSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);

  const client = await getPool().connect();
  try {
    await client.query('BEGIN');
    const flow = transactionFlowSql('transaction', 'account');
    const transactionResult = await client.query<TransactionForCategory>(
      `SELECT
         transaction.id::text,
         transaction.merchant_id::text,
         (${flow}) AS flow_type
       FROM txn AS transaction
       JOIN account ON account.id = transaction.account_id
       WHERE transaction.id = $1::uuid
       FOR UPDATE OF transaction`,
      [id.data]
    );
    const transaction = transactionResult.rows[0];
    if (!transaction) {
      await client.query('ROLLBACK');
      return apiError(404, 'transaction_not_found', 'That transaction was not found.');
    }
    const categoryResult = await client.query<{ id: string; name: string; kind: CategoryKind }>(
      `SELECT id::text, name, kind
       FROM category
       WHERE id = $1::uuid AND archived_at IS NULL`,
      [parsed.data.categoryId]
    );
    const category = categoryResult.rows[0];
    if (!category) {
      await client.query('ROLLBACK');
      return apiError(400, 'category_not_found', 'Choose an active category.');
    }
    if (category.kind !== expectedCategoryKind[transaction.flow_type]) {
      await client.query('ROLLBACK');
      return apiError(400, 'category_incompatible', 'That category does not match the transaction flow.');
    }

    let merchantTransactionsUpdated = 0;
    let categorySource: 'user_transaction' | 'user_merchant' = 'user_transaction';
    if (parsed.data.applyToMerchant) {
      if (!transaction.merchant_id) {
        await client.query('ROLLBACK');
        return apiError(400, 'merchant_unavailable', 'This transaction has no merchant mapping to reuse.');
      }
      categorySource = 'user_merchant';
      await client.query(
        `INSERT INTO merchant_category_mapping (
           merchant_id, flow_type, category_id, source, confidence
         ) VALUES ($1::uuid, $2, $3::uuid, 'user_merchant', 1)
         ON CONFLICT (merchant_id, flow_type) DO UPDATE
         SET category_id = EXCLUDED.category_id,
             source = 'user_merchant',
             confidence = 1,
             updated_at = now()`,
        [transaction.merchant_id, transaction.flow_type, category.id]
      );
      const updated = await client.query(
        `UPDATE txn AS candidate
         SET category_id = $1::uuid,
             category_source = 'user_merchant',
             category_confidence = 1,
             updated_at = now()
         FROM account
         WHERE account.id = candidate.account_id
           AND candidate.merchant_id = $2::uuid
           AND candidate.id <> $3::uuid
           AND (${transactionFlowSql('candidate', 'account')}) = $4
           AND candidate.category_source <> 'user_transaction'`,
        [category.id, transaction.merchant_id, transaction.id, transaction.flow_type]
      );
      merchantTransactionsUpdated = updated.rowCount ?? 0;
    }

    await client.query(
      `UPDATE txn
       SET category_id = $2::uuid,
           category_source = $3,
           category_confidence = 1,
           updated_at = now()
       WHERE id = $1::uuid`,
      [transaction.id, category.id, categorySource]
    );
    await client.query('COMMIT');
    return json(
      {
        transaction: {
          id: transaction.id,
          categoryId: category.id,
          categoryName: category.name,
          categorySource,
          categoryConfidence: '1.0000'
        },
        merchantTransactionsUpdated
      },
      { headers: { 'cache-control': 'no-store' } }
    );
  } catch (error) {
    await client.query('ROLLBACK');
    return unavailableOrInternal(error, 'update transaction category');
  } finally {
    client.release();
  }
}
