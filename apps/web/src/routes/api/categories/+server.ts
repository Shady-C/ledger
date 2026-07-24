import { json } from '@sveltejs/kit';

import { privateReadHeaders, unavailableOrInternal } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';

type CategoryRow = {
  id: string;
  parent_id: string | null;
  name: string;
  kind: 'spend' | 'income' | 'transfer' | 'fee';
};

export async function GET() {
  try {
    const result = await query<CategoryRow>(`
      SELECT id, parent_id, name, kind
      FROM category
      ORDER BY parent_id NULLS FIRST, name
    `);
    return json(
      {
        categories: result.rows.map((row) => ({
          id: row.id,
          parentId: row.parent_id,
          name: row.name,
          kind: row.kind
        }))
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'categories');
  }
}
