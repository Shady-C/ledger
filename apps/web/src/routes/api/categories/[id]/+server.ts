import { json } from '@sveltejs/kit';
import { categoryPatchSchema, uuidSchema } from '@ledger/shared-types';

import { apiError, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';
import { postgresErrorCode } from '$lib/server/phase1.js';

type CategoryRow = {
  id: string;
  parent_id: string | null;
  name: string;
  kind: 'spend' | 'income' | 'transfer' | 'fee';
  archived_at: Date | null;
  is_protected: boolean;
};

const publicCategory = (row: CategoryRow) => ({
  id: row.id,
  parentId: row.parent_id,
  name: row.name,
  kind: row.kind,
  archivedAt: row.archived_at?.toISOString() ?? null,
  isProtected: row.is_protected
});

export async function PATCH({ params, request }) {
  const id = uuidSchema.safeParse(params.id);
  if (!id.success) return apiError(400, 'invalid_category', 'The category id is invalid.');
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON category payload.');
  }
  const parsed = categoryPatchSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);

  try {
    const current = await query<CategoryRow>(
      `SELECT id::text, parent_id::text, name, kind, archived_at, is_protected
       FROM category WHERE id = $1::uuid`,
      [id.data]
    );
    const existing = current.rows[0];
    if (!existing) return apiError(404, 'category_not_found', 'That category was not found.');
    if (existing.is_protected) {
      return apiError(409, 'protected_category', 'The fallback category cannot be changed or archived.');
    }

    const nextParent = 'parentId' in parsed.data ? parsed.data.parentId ?? null : existing.parent_id;
    const nextKind = parsed.data.kind ?? existing.kind;
    if (nextParent === id.data) {
      return apiError(400, 'invalid_parent_category', 'A category cannot be its own parent.');
    }
    if (nextParent) {
      const parent = await query<{ valid: boolean }>(
        `SELECT EXISTS (
           SELECT 1 FROM category
           WHERE id = $1::uuid AND archived_at IS NULL AND kind = $2
         ) AS valid`,
        [nextParent, nextKind]
      );
      if (!parent.rows[0]?.valid) {
        return apiError(400, 'invalid_parent_category', 'The parent category is missing, archived, or incompatible.');
      }
    }

    const values: unknown[] = [];
    const updates: string[] = [];
    const add = (column: string, value: unknown, cast = '') => {
      values.push(value);
      updates.push(`${column} = $${values.length}${cast}`);
    };
    if ('parentId' in parsed.data) add('parent_id', parsed.data.parentId, '::uuid');
    if (parsed.data.name !== undefined) add('name', parsed.data.name);
    if (parsed.data.kind !== undefined) add('kind', parsed.data.kind);
    if (parsed.data.archived !== undefined) {
      updates.push(`archived_at = ${parsed.data.archived ? 'now()' : 'NULL'}`);
    }
    values.push(id.data);
    const result = await query<CategoryRow>(
      `UPDATE category
       SET ${updates.join(', ')}, updated_at = now()
       WHERE id = $${values.length}::uuid
       RETURNING id::text, parent_id::text, name, kind, archived_at, is_protected`,
      values
    );
    return json(
      { category: publicCategory(result.rows[0]!) },
      { headers: { 'cache-control': 'no-store' } }
    );
  } catch (error) {
    if (postgresErrorCode(error) === '23505') {
      return apiError(409, 'category_exists', 'A category with that name already exists at this level.');
    }
    if (postgresErrorCode(error) === '23514') {
      return apiError(409, 'category_update_conflict', 'That category update violates a taxonomy constraint.');
    }
    return unavailableOrInternal(error, 'update category');
  }
}
