import { json } from '@sveltejs/kit';
import { insightSummaryQuerySchema } from '@ledger/shared-types';

import { privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { readInsightSummary } from '$lib/server/insights.js';

export async function GET({ url }) {
  const parsed = insightSummaryQuerySchema.safeParse(Object.fromEntries(url.searchParams));
  if (!parsed.success) return validationError(parsed.error);
  try {
    return json(await readInsightSummary(parsed.data), { headers: privateReadHeaders });
  } catch (error) {
    return unavailableOrInternal(error, 'insights summary');
  }
}
