import { json } from '@sveltejs/kit';
import { accountCreateSchema, optionalMarketQuerySchema } from '@ledger/shared-types';

import { apiError, privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
import {
  buildAccountsSummaryQuery,
  buildCreditUtilizationSummaryQuery,
  getPool,
  query
} from '$lib/server/db.js';
import {
  mapAccountSummary,
  postgresErrorCode,
  readAccountSummary,
  type AccountSummaryRow
} from '$lib/server/phase1.js';

type CreditUtilizationRow = {
  base_currency: string;
  used_credit_base: string;
  credit_limit_base: string;
  available_credit_base: string;
  utilization_percent: string | null;
  included_account_count: number;
  excluded_accounts: Array<{
    accountId: string;
    displayName: string;
    reason: 'missing_credit_limit' | 'unverified_balance' | 'missing_fx_rate';
  }>;
};

export async function GET({ url }) {
  const market = optionalMarketQuerySchema.safeParse(url.searchParams.get('market'));
  if (!market.success) return validationError(market.error);
  const client = await getPool().connect();
  try {
    await client.query('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY');
    const built = buildAccountsSummaryQuery(undefined, market.data);
    const utilizationBuilt = buildCreditUtilizationSummaryQuery(market.data);
    const result = await client.query<AccountSummaryRow>(built.text, built.values);
    const utilizationResult = await client.query<CreditUtilizationRow>(utilizationBuilt.text, utilizationBuilt.values);
    const utilization = utilizationResult.rows[0];
    if (!utilization) throw new Error('Credit utilization summary could not be read');
    await client.query('COMMIT');

    return json(
      {
        accounts: result.rows.map(mapAccountSummary),
        creditUtilization: {
          baseCurrency: utilization.base_currency,
          usedCreditBase: utilization.used_credit_base,
          creditLimitBase: utilization.credit_limit_base,
          availableCreditBase: utilization.available_credit_base,
          utilizationPercent: utilization.utilization_percent,
          includedAccountCount: utilization.included_account_count,
          excludedAccounts: utilization.excluded_accounts
        }
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    await client.query('ROLLBACK').catch(() => undefined);
    return unavailableOrInternal(error, 'accounts');
  } finally {
    client.release();
  }
}

export async function POST({ request }) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON account payload.');
  }
  const parsed = accountCreateSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);

  try {
    const inserted = await query<{ id: string }>(
       `INSERT INTO account (
         institution_id, display_name, kind, native_currency, market_code,
         account_ref_masked, credit_limit
       ) VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::numeric)
       RETURNING id::text`,
      [
        parsed.data.institutionId ?? null,
        parsed.data.displayName,
        parsed.data.kind,
        parsed.data.nativeCurrency,
        parsed.data.marketCode,
        parsed.data.accountRefMasked ?? null,
        parsed.data.creditLimit ?? null
      ]
    );
    const id = inserted.rows[0]?.id;
    if (!id) throw new Error('Account insert did not return an id');
    const account = await readAccountSummary(id);
    if (!account) throw new Error('Created account could not be read');
    return json({ account }, { status: 201, headers: { 'cache-control': 'no-store' } });
  } catch (error) {
    if (postgresErrorCode(error) === '23503') {
      return apiError(400, 'invalid_institution', 'The selected institution does not exist.');
    }
    if (postgresErrorCode(error) === '23514') {
      return apiError(400, 'invalid_account', 'The account values violate a financial constraint.');
    }
    return unavailableOrInternal(error, 'create account');
  }
}
