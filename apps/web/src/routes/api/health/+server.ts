import { json } from '@sveltejs/kit';

import { query } from '$lib/server/db.js';

export async function GET() {
  try {
    await query('SELECT 1');
    return json(
      { status: 'ready' },
      { headers: { 'cache-control': 'no-store' } }
    );
  } catch (error) {
    console.error('[health] readiness check failed', error);
    return json(
      { status: 'unavailable' },
      { status: 503, headers: { 'cache-control': 'no-store' } }
    );
  }
}
