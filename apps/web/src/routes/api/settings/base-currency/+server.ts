import { json } from '@sveltejs/kit';
import { baseCurrencyChangeSchema } from '@ledger/shared-types';

import { apiError, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';
import { enqueueJob } from '$lib/server/phase1.js';

export async function POST({ request }) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON base-currency payload.');
  }
  const parsed = baseCurrencyChangeSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);
  if (parsed.data.baseCurrency !== 'CAD') {
    return apiError(
      409,
      'base_currency_fixed',
      'Phase 2 keeps CAD as the fixed reporting currency; account-native values remain unchanged.'
    );
  }

  try {
    const target = parsed.data.baseCurrency;
    const accepted = await enqueueJob(
      'base_currency_rebuild',
      { target_base_currency: target },
      'base_currency_rebuild:ledger'
    );
    const acceptedTarget = await query<{ target_base_currency: string | null }>(
      `SELECT payload ->> 'target_base_currency' AS target_base_currency
       FROM job
       WHERE id = $1::uuid`,
      [accepted.jobId]
    );
    if (acceptedTarget.rows[0]?.target_base_currency !== target) {
      return apiError(
        409,
        'base_currency_rebuild_in_progress',
        'Another base-currency rebuild is already in progress. Retry after it completes.'
      );
    }
    return json(accepted, {
      status: accepted.status === 'queued' ? 202 : 200,
      headers: { 'cache-control': 'no-store', location: `/api/jobs/${accepted.jobId}` }
    });
  } catch (error) {
    return unavailableOrInternal(error, 'change base currency');
  }
}
