import { json } from '@sveltejs/kit';
import { insightRecurringQuerySchema } from '@ledger/shared-types';

import { privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { readInsightRecurring } from '$lib/server/insights.js';

export async function GET({ url }) {
  const parsed = insightRecurringQuerySchema.safeParse(Object.fromEntries(url.searchParams));
  if (!parsed.success) return validationError(parsed.error);
  try {
    return json(await readInsightRecurring(parsed.data), { headers: privateReadHeaders });
  } catch (error) {
    return unavailableOrInternal(error, 'insights recurring');
  }
}
