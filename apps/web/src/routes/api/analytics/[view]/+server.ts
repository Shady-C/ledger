import { json } from '@sveltejs/kit';
import { analyticsQuerySchema, analyticsViewSchema } from '@ledger/shared-types';

import {
  apiError,
  privateReadHeaders,
  unavailableOrInternal,
  validationError
} from '$lib/server/api.js';
import { buildBalanceQuery, buildCashflowQuery, query } from '$lib/server/db.js';

type BalanceRow = { date: string; balance: string };
type CashflowRow = { period: string; inflow: string; outflow: string; net: string };

export async function GET({ params, url }) {
  const view = analyticsViewSchema.safeParse(params.view);
  if (!view.success) return apiError(404, 'view_not_found', 'That analytics view is not available.');

  const parsed = analyticsQuerySchema.safeParse(Object.fromEntries(url.searchParams));
  if (!parsed.success) return validationError(parsed.error);

  const currency = process.env.BASE_CURRENCY?.trim().toUpperCase() || 'CAD';
  try {
    if (view.data === 'balance') {
      const built = buildBalanceQuery(parsed.data);
      const result = await query<BalanceRow>(built.text, built.values);
      return json(
        { currency, points: result.rows },
        { headers: privateReadHeaders }
      );
    }

    const built = buildCashflowQuery(parsed.data);
    const result = await query<CashflowRow>(built.text, built.values);
    return json(
      { currency, points: result.rows },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    return unavailableOrInternal(error, `analytics ${view.data}`);
  }
}
