import { json } from '@sveltejs/kit';
import { recurringPatchSchema, uuidSchema } from '@ledger/shared-types';

import { apiError, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { updateRecurringSeries } from '$lib/server/insights.js';

export async function PATCH({ params, request }) {
  const id = uuidSchema.safeParse(params.id);
  if (!id.success) return apiError(400, 'invalid_recurring_series', 'The recurring-series id is invalid.');
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON recurring-series payload.');
  }
  const parsed = recurringPatchSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);
  try {
    const series = await updateRecurringSeries(id.data, parsed.data);
    if (!series) return apiError(404, 'recurring_series_not_found', 'That recurring series was not found.');
    return json({ series }, { headers: { 'cache-control': 'no-store' } });
  } catch (error) {
    return unavailableOrInternal(error, 'update recurring series');
  }
}
