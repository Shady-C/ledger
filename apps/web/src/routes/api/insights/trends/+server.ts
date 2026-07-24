import { json } from '@sveltejs/kit';
import { insightTrendsQuerySchema } from '@ledger/shared-types';

import { privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { readInsightTrends } from '$lib/server/insights.js';

export async function GET({ url }) {
  const parsed = insightTrendsQuerySchema.safeParse(Object.fromEntries(url.searchParams));
  if (!parsed.success) return validationError(parsed.error);
  try {
    return json(await readInsightTrends(parsed.data), { headers: privateReadHeaders });
  } catch (error) {
    return unavailableOrInternal(error, 'insights trends');
  }
}
