import { json } from '@sveltejs/kit';
import { insightFindingsQuerySchema } from '@ledger/shared-types';

import { privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { readInsightFindings } from '$lib/server/insights.js';

export async function GET({ url }) {
  const parsed = insightFindingsQuerySchema.safeParse(Object.fromEntries(url.searchParams));
  if (!parsed.success) return validationError(parsed.error);
  try {
    return json(await readInsightFindings(parsed.data), { headers: privateReadHeaders });
  } catch (error) {
    return unavailableOrInternal(error, 'insights findings');
  }
}
