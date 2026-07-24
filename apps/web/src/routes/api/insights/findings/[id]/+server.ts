import { json } from '@sveltejs/kit';
import { insightFindingPatchSchema, uuidSchema } from '@ledger/shared-types';

import { apiError, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { updateInsightFinding } from '$lib/server/insights.js';

export async function PATCH({ params, request }) {
  const id = uuidSchema.safeParse(params.id);
  if (!id.success) return apiError(400, 'invalid_finding', 'The finding id is invalid.');
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON finding payload.');
  }
  const parsed = insightFindingPatchSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);
  try {
    const finding = await updateInsightFinding(id.data, parsed.data);
    if (!finding) return apiError(404, 'finding_not_found', 'That finding was not found.');
    return json({ finding }, { headers: { 'cache-control': 'no-store' } });
  } catch (error) {
    return unavailableOrInternal(error, 'review insight finding');
  }
}
