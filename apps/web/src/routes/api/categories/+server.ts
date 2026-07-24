import { json } from '@sveltejs/kit';
import { categoryCreateSchema } from '@ledger/shared-types';

import { apiError, privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
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

function mapCategory(row: CategoryRow) {
  return {
    id: row.id,
    parentId: row.parent_id,
    name: row.name,
    kind: row.kind,
    archivedAt: row.archived_at?.toISOString() ?? null,
    isProtected: row.is_protected
  };
}

export async function GET() {
  try {
    const result = await query<CategoryRow>(`
      SELECT id::text, parent_id::text, name, kind, archived_at, is_protected
      FROM category
      ORDER BY parent_id NULLS FIRST, name
    `);
    return json(
      {
        categories: result.rows.map(mapCategory)
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'categories');
  }
}

export async function POST({ request }) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON category payload.');
  }
  const parsed = categoryCreateSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);

  try {
    const result = await query<CategoryRow>(
      `INSERT INTO category (parent_id, name, kind)
       SELECT $1::uuid, $2, $3
       WHERE $1::uuid IS NULL OR EXISTS (
         SELECT 1
         FROM category parent
         WHERE parent.id = $1::uuid
           AND parent.archived_at IS NULL
           AND parent.kind = $3
       )
       RETURNING id::text, parent_id::text, name, kind, archived_at, is_protected`,
      [parsed.data.parentId ?? null, parsed.data.name, parsed.data.kind]
    );
    const category = result.rows[0];
    if (!category) {
      return apiError(400, 'invalid_parent_category', 'The parent category is missing, archived, or incompatible.');
    }
    return json({ category: mapCategory(category) }, { status: 201, headers: { 'cache-control': 'no-store' } });
  } catch (error) {
    if (postgresErrorCode(error) === '23505') {
      return apiError(409, 'category_exists', 'A category with that name already exists at this level.');
    }
    return unavailableOrInternal(error, 'create category');
  }
}
