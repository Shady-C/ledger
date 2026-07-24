import { json } from '@sveltejs/kit';
import { analyticsQuerySchema, analyticsViewSchema } from '@ledger/shared-types';

import {
  apiError,
  privateReadHeaders,
  unavailableOrInternal,
  validationError
} from '$lib/server/api.js';
import {
  buildBalanceQuery,
  buildCashflowQuery,
  buildFxAnalyticsQuery,
  buildNetWorthQuery,
  getPool
} from '$lib/server/db.js';

type BalanceRow = { date: string; balance: string; basis: 'balance' | 'net_activity' };
type CashflowRow = {
  period: string;
  inflow: string;
  outflow: string;
  card_payments: string;
  net: string;
};
type NetWorthRow = {
  account_id: string;
  display_name: string;
  kind: 'credit_card' | 'chequing' | 'savings' | 'wallet';
  native_currency: string;
  native_balance: string;
  base_value: string | null;
  contribution: string | null;
  fx_rate: string | null;
  fx_rate_date: string | null;
  excluded_reason: 'unverified_balance' | 'missing_fx_rate' | null;
  assets: string;
  liabilities: string;
  net_worth: string;
  base_currency: string;
  is_partial: boolean;
  valuation_date: string;
};
type FxRow = {
  transaction_id: string;
  account_id: string;
  account_name: string;
  booked_date: string;
  description_raw: string;
  foreign_amount: string;
  foreign_currency: string;
  charged_amount_native: string;
  native_currency: string;
  card_applied_rate: string;
  market_rate: string | null;
  market_rate_date: string | null;
  market_rate_source: string | null;
  markup_percent: string | null;
  estimated_fee_native: string | null;
  estimated_fee_base: string | null;
  base_currency: string;
  total_estimated_fee_base: string;
};

export async function GET({ params, url }) {
  const view = analyticsViewSchema.safeParse(params.view);
  if (!view.success) return apiError(404, 'view_not_found', 'That analytics view is not available.');

  const parsed = analyticsQuerySchema.safeParse(Object.fromEntries(url.searchParams));
  if (!parsed.success) return validationError(parsed.error);

  const client = await getPool().connect();
  let committed = false;
  try {
    await client.query('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY');
    const settings = await client.query<{ base_currency: string }>(
      'SELECT base_currency FROM ledger_settings WHERE singleton'
    );
    const currency = settings.rows[0]?.base_currency;
    if (!currency) throw new Error('Ledger settings row is missing');

    if (view.data === 'balance') {
      const built = buildBalanceQuery(parsed.data);
      const result = await client.query<BalanceRow>(built.text, built.values);
      await client.query('COMMIT');
      committed = true;
      return json(
        {
          currency,
          basis: result.rows[0]?.basis ?? 'net_activity',
          points: result.rows.map(({ date, balance }) => ({ date, balance }))
        },
        { headers: privateReadHeaders }
      );
    }

    if (view.data === 'net-worth') {
      const built = buildNetWorthQuery(parsed.data.accountId);
      const result = await client.query<NetWorthRow>(built.text, built.values);
      const summary = result.rows[0];
      await client.query('COMMIT');
      committed = true;
      return json(
        {
          baseCurrency: summary?.base_currency ?? currency,
          valuationDate: summary?.valuation_date ?? new Date().toISOString().slice(0, 10),
          status: result.rows.some((row) => row.excluded_reason !== null) ? 'partial' : 'complete',
          assets: summary?.assets ?? '0',
          liabilities: summary?.liabilities ?? '0',
          netWorth: summary?.net_worth ?? '0',
          accounts: result.rows
            .filter(
              (row): row is NetWorthRow & {
                base_value: string;
                contribution: string;
                fx_rate: string;
                fx_rate_date: string;
              } => row.excluded_reason === null
                && row.base_value !== null
                && row.contribution !== null
                && row.fx_rate !== null
                && row.fx_rate_date !== null
            )
            .map((row) => ({
              accountId: row.account_id,
              displayName: row.display_name,
              kind: row.kind,
              nativeBalance: row.native_balance,
              nativeCurrency: row.native_currency,
              baseValue: row.base_value,
              contribution: row.contribution,
              fxRate: row.fx_rate,
              fxRateDate: row.fx_rate_date
            })),
          excludedAccounts: result.rows
            .filter(
              (row): row is NetWorthRow & {
                excluded_reason: 'unverified_balance' | 'missing_fx_rate';
              } => row.excluded_reason !== null
            )
            .map((row) => ({
              accountId: row.account_id,
              displayName: row.display_name,
              reason: row.excluded_reason
            }))
        },
        { headers: privateReadHeaders }
      );
    }

    if (view.data === 'fx') {
      const built = buildFxAnalyticsQuery(parsed.data);
      const result = await client.query<FxRow>(built.text, built.values);
      await client.query('COMMIT');
      committed = true;
      return json(
        {
          baseCurrency: result.rows[0]?.base_currency ?? currency,
          totalEstimatedFeeBase: result.rows[0]?.total_estimated_fee_base ?? '0',
          transactions: result.rows.map((row) => ({
            transactionId: row.transaction_id,
            accountId: row.account_id,
            accountName: row.account_name,
            bookedDate: row.booked_date,
            description: row.description_raw,
            foreignAmount: row.foreign_amount,
            foreignCurrency: row.foreign_currency,
            chargedAmountNative: row.charged_amount_native,
            nativeCurrency: row.native_currency,
            cardAppliedRate: row.card_applied_rate,
            marketRate: row.market_rate,
            marketRateDate: row.market_rate_date,
            marketRateSource: row.market_rate_source,
            markupPercent: row.markup_percent,
            estimatedFeeNative: row.estimated_fee_native,
            estimatedFeeBase: row.estimated_fee_base
          }))
        },
        { headers: privateReadHeaders }
      );
    }

    const built = buildCashflowQuery(parsed.data);
    const result = await client.query<CashflowRow>(built.text, built.values);
    await client.query('COMMIT');
    committed = true;
    return json(
      {
        currency,
        points: result.rows.map(({ card_payments, ...row }) => ({
          ...row,
          cardPayments: card_payments
        }))
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    if (!committed) await client.query('ROLLBACK').catch(() => undefined);
    return unavailableOrInternal(error, `analytics ${view.data}`);
  } finally {
    client.release();
  }
}
