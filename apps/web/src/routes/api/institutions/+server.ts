import { json } from '@sveltejs/kit';
import { institutionWriteSchema } from '@ledger/shared-types';

import { apiError, privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';
import { postgresErrorCode } from '$lib/server/phase1.js';

type InstitutionRow = { id: string; name: string };

export async function GET() {
  try {
    const result = await query<InstitutionRow>(
      'SELECT id::text, name FROM institution ORDER BY lower(name), id'
    );
    return json({ institutions: result.rows }, { headers: privateReadHeaders });
  } catch (error) {
    return unavailableOrInternal(error, 'institutions');
  }
}

export async function POST({ request }) {
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
      `INSERT INTO institution (name)
       VALUES ($1)
       RETURNING id::text, name`,
      [parsed.data.name]
    );
    return json({ institution: result.rows[0] }, { status: 201, headers: { 'cache-control': 'no-store' } });
  } catch (error) {
    if (postgresErrorCode(error) === '23505') {
      return apiError(409, 'institution_exists', 'An institution with that name already exists.');
    }
    return unavailableOrInternal(error, 'create institution');
  }
}
