import { json } from '@sveltejs/kit';
import {
  optionalMarketQuerySchema,
  transactionCategoryPatchSchema,
  uuidSchema,
  type CategoryKind,
  type TransactionQuery,
  type TransactionFlowType
} from '@ledger/shared-types';
import type { PoolClient } from 'pg';

import { apiError, privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { buildFxAnalyticsQuery, buildTransactionQueries, getPool, transactionFlowSql } from '$lib/server/db.js';
import { enqueueAnalyticsRefresh } from '$lib/server/insights.js';
import {
  mapTransactionRow,
  transactionExplicitFeeEvidence,
  type TransactionRow
} from '$lib/server/transactions.js';

type FxDetailRow = {
  bank_applied_rate: string | null;
  market_rate: string | null;
  market_rate_date: string | null;
  market_rate_source: string | null;
  explicit_fee_native: string;
  explicit_fee_base: string | null;
  estimated_markup_native: string | null;
  estimated_markup_base: string | null;
};

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

export async function GET({ params, url }) {
  const id = uuidSchema.safeParse(params.id);
  if (!id.success) return apiError(400, 'invalid_transaction', 'The transaction id is invalid.');
  const market = optionalMarketQuerySchema.safeParse(url.searchParams.get('market'));
  if (!market.success) return validationError(market.error);

  const spec: TransactionQuery = {
    sort: 'booked_date_desc',
    page: 1,
    pageSize: 1,
    ...(market.data ? { market: market.data } : {})
  };
  const transactionQuery = buildTransactionQueries(spec, id.data).data;
  const fxQuery = buildFxAnalyticsQuery(
    market.data ? { market: market.data } : {},
    id.data
  );
  let client: PoolClient | undefined;
  try {
    client = await getPool().connect();
    await client.query('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY');
    const [transactionResult, fxResult] = await Promise.all([
      client.query<TransactionRow>(transactionQuery.text, transactionQuery.values),
      client.query<FxDetailRow>(fxQuery.text, fxQuery.values)
    ]);
    const row = transactionResult.rows[0];
    if (!row) {
      await client.query('ROLLBACK');
      return apiError(404, 'transaction_not_found', 'That transaction was not found.');
    }
    await client.query('COMMIT');
    const transaction = mapTransactionRow(row);
    const fx = fxResult.rows[0];
    const explicitFee = transactionExplicitFeeEvidence(row, fx);
    return json(
      {
        transaction,
        conversionEvidence: {
          indicators: transaction.conversionIndicators,
          valuationStatus: transaction.valuationStatus,
          original: transaction.originalAmount !== null && transaction.originalCurrency !== null
            ? { amount: transaction.originalAmount, currency: transaction.originalCurrency }
            : null,
          posted: { amount: transaction.amountNative, currency: transaction.currencyNative },
          reporting: transaction.amountBase !== null
            ? { amount: transaction.amountBase, currency: transaction.currencyBase }
            : null,
          reportingRate: transaction.fxRate,
          reportingRateDate: transaction.fxRateDate,
          bankAppliedRate: fx?.bank_applied_rate ?? null,
          referenceRate: fx?.market_rate ?? null,
          referenceRateDate: fx?.market_rate_date ?? null,
          referenceRateSource: fx?.market_rate_source ?? null,
          ...explicitFee,
          estimatedMarkupNative: fx?.estimated_markup_native ?? null,
          estimatedMarkupBase: fx?.estimated_markup_base ?? null,
          runningBalanceNative: row.running_balance_native,
          runningBalanceBase: row.running_balance_base
        }
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    if (client) await client.query('ROLLBACK').catch(() => undefined);
    return unavailableOrInternal(error, 'transaction detail');
  } finally {
    client?.release();
  }
}

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
    await enqueueAnalyticsRefresh('incremental').catch(() => undefined);
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
