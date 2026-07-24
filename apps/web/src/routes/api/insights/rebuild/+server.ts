import { json } from '@sveltejs/kit';
import { insightRebuildRequestSchema } from '@ledger/shared-types';

import { apiError, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { enqueueAnalyticsRefresh } from '$lib/server/insights.js';

export async function POST({ request }) {
  let body: unknown = {};
  try {
    const raw = await request.text();
    body = raw ? JSON.parse(raw) : {};
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON analytics-refresh payload.');
  }
  const parsed = insightRebuildRequestSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);
  try {
    const accepted = await enqueueAnalyticsRefresh(parsed.data.mode);
    return json(accepted, {
      status: accepted.status === 'queued' ? 202 : 200,
      headers: {
        'cache-control': 'no-store',
        location: `/api/jobs/${accepted.jobId}`
      }
    });
  } catch (error) {
    return unavailableOrInternal(error, 'rebuild insights');
  }
}
