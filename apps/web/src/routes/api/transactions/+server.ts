import { json } from '@sveltejs/kit';
import { transactionQuerySchema } from '@ledger/shared-types';
import type { PoolClient } from 'pg';

import {
  privateReadHeaders,
  unavailableOrInternal,
  validationError
} from '$lib/server/api.js';
import { buildTransactionQueries, getPool } from '$lib/server/db.js';
import { mapTransactionRow, type TransactionRow } from '$lib/server/transactions.js';
type CountRow = { total: number };

export async function GET({ url }) {
  const parsed = transactionQuerySchema.safeParse(Object.fromEntries(url.searchParams));
  if (!parsed.success) return validationError(parsed.error);

  let client: PoolClient | undefined;
  try {
    client = await getPool().connect();
    await client.query('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY');
    const built = buildTransactionQueries(parsed.data);
    const data = await client.query<TransactionRow>(built.data.text, built.data.values);
    const count = await client.query<CountRow>(built.count.text, built.count.values);
    const total = count.rows[0]?.total ?? 0;
    await client.query('COMMIT');
    return json(
      {
        items: data.rows.map(mapTransactionRow),
        page: parsed.data.page,
        pageSize: parsed.data.pageSize,
        total,
        totalPages: total === 0 ? 0 : Math.ceil(total / parsed.data.pageSize)
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    if (client) await client.query('ROLLBACK').catch(() => undefined);
    return unavailableOrInternal(error, 'transactions');
  } finally {
    client?.release();
  }
}
