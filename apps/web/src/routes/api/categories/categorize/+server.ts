import { json } from '@sveltejs/kit';
import { categorizationRequestSchema } from '@ledger/shared-types';

import { apiError, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { enqueueJob } from '$lib/server/phase1.js';

export async function POST({ request }) {
  let body: unknown = {};
  const text = await request.text();
  if (text.trim()) {
    try {
      body = JSON.parse(text);
    } catch {
      return apiError(400, 'invalid_json', 'Expected a JSON categorization payload.');
    }
  }
  const parsed = categorizationRequestSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);

  try {
    const accepted = await enqueueJob(
      'categorize',
      { mode: parsed.data.mode },
      `categorize:${parsed.data.mode}`
    );
    return json(accepted, {
      status: accepted.status === 'queued' ? 202 : 200,
      headers: { 'cache-control': 'no-store', location: `/api/jobs/${accepted.jobId}` }
    });
  } catch (error) {
    return unavailableOrInternal(error, 'categorize transactions');
  }
}
