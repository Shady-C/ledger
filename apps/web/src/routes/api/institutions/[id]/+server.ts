import { json } from '@sveltejs/kit';
import { institutionWriteSchema, uuidSchema } from '@ledger/shared-types';

import { apiError, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';
import { postgresErrorCode } from '$lib/server/phase1.js';

type InstitutionRow = { id: string; name: string };

export async function PATCH({ params, request }) {
  const id = uuidSchema.safeParse(params.id);
  if (!id.success) return apiError(400, 'invalid_institution', 'The institution id is invalid.');
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON institution payload.');
  }
  const parsed = institutionWriteSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);

  try {
    const result = await query<InstitutionRow>(
      `UPDATE institution
       SET name = $1, updated_at = now()
       WHERE id = $2::uuid
       RETURNING id::text, name`,
      [parsed.data.name, id.data]
    );
    const institution = result.rows[0];
    if (!institution) return apiError(404, 'institution_not_found', 'That institution was not found.');
    return json({ institution }, { headers: { 'cache-control': 'no-store' } });
  } catch (error) {
    if (postgresErrorCode(error) === '23505') {
      return apiError(409, 'institution_exists', 'An institution with that name already exists.');
    }
    return unavailableOrInternal(error, 'update institution');
  }
}
