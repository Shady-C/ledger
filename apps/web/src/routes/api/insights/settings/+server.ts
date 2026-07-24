import { json } from '@sveltejs/kit';
import { insightSettingsPatchSchema } from '@ledger/shared-types';

import {
  apiError,
  privateReadHeaders,
  unavailableOrInternal,
  validationError
} from '$lib/server/api.js';
import { readInsightSettings, updateInsightSettings } from '$lib/server/insights.js';

export async function GET() {
  try {
    return json(await readInsightSettings(), { headers: privateReadHeaders });
  } catch (error) {
    return unavailableOrInternal(error, 'insights settings');
  }
}

export async function PATCH({ request }) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON Insights settings payload.');
  }
  const parsed = insightSettingsPatchSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);
  try {
    return json(await updateInsightSettings(parsed.data), { headers: { 'cache-control': 'no-store' } });
  } catch (error) {
    return unavailableOrInternal(error, 'update insights settings');
  }
}
