import { json } from '@sveltejs/kit';
import { accountPatchSchema, uuidSchema } from '@ledger/shared-types';

import { apiError, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';
import { postgresErrorCode, readAccountSummary } from '$lib/server/phase1.js';

export async function PATCH({ params, request }) {
  const id = uuidSchema.safeParse(params.id);
  if (!id.success) return apiError(400, 'invalid_account', 'The account id is invalid.');

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON account payload.');
  }
  const parsed = accountPatchSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);

  const values: unknown[] = [];
  const updates: string[] = [];
  const add = (column: string, value: unknown, cast = '') => {
    values.push(value);
    updates.push(`${column} = $${values.length}${cast}`);
  };
  if ('institutionId' in parsed.data) add('institution_id', parsed.data.institutionId, '::uuid');
  if (parsed.data.displayName !== undefined) add('display_name', parsed.data.displayName);
  if (parsed.data.kind !== undefined) add('kind', parsed.data.kind);
  if (parsed.data.nativeCurrency !== undefined) add('native_currency', parsed.data.nativeCurrency);
  if ('accountRefMasked' in parsed.data) add('account_ref_masked', parsed.data.accountRefMasked);
  if ('creditLimit' in parsed.data) add('credit_limit', parsed.data.creditLimit, '::numeric');
  values.push(id.data);

  try {
    const updated = await query<{ id: string }>(
      `UPDATE account
       SET ${updates.join(', ')}, updated_at = now()
       WHERE id = $${values.length}::uuid
       RETURNING id::text`,
      values
    );
    if (!updated.rows[0]) return apiError(404, 'account_not_found', 'That account was not found.');
    const account = await readAccountSummary(id.data);
    if (!account) throw new Error('Updated account could not be read');
    return json({ account }, { headers: { 'cache-control': 'no-store' } });
  } catch (error) {
    if (postgresErrorCode(error) === '23503') {
      return apiError(400, 'invalid_institution', 'The selected institution does not exist.');
    }
    if (postgresErrorCode(error) === '23514') {
      return apiError(
        409,
        'account_update_conflict',
        'Account kind and currency cannot change after transactions or statements exist.'
      );
    }
    return unavailableOrInternal(error, 'update account');
  }
}
