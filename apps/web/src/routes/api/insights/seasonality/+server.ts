import { json } from '@sveltejs/kit';
import { insightSeasonalityQuerySchema } from '@ledger/shared-types';

import { apiError, privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { AnalyticsRebuildingError, readInsightSeasonality } from '$lib/server/insights.js';

export async function GET({ url }) {
  const parsed = insightSeasonalityQuerySchema.safeParse(Object.fromEntries(url.searchParams));
  if (!parsed.success) return validationError(parsed.error);
  try {
    return json(await readInsightSeasonality(parsed.data), { headers: privateReadHeaders });
  } catch (error) {
    if (error instanceof AnalyticsRebuildingError) return apiError(503, 'analytics_rebuilding', error.message);
    return unavailableOrInternal(error, 'insights seasonality');
  }
}
