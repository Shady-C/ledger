import { json } from '@sveltejs/kit';
import { jobQuerySchema } from '@ledger/shared-types';

import { privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';

type JobListRow = {
  id: string;
  kind: 'ingest' | 'categorize' | 'fx_refresh' | 'base_currency_rebuild';
  status: 'queued' | 'claimed' | 'done' | 'failed' | 'needs_ai';
  created_at: Date;
  finished_at: Date | null;
  retry_count: number;
  max_retries: number;
};

export async function GET({ url }) {
  const parsed = jobQuerySchema.safeParse(Object.fromEntries(url.searchParams));
  if (!parsed.success) return validationError(parsed.error);

  const values: unknown[] = [];
  const conditions: string[] = [];
  const add = (value: unknown) => {
    values.push(value);
    return `$${values.length}`;
  };
  if (parsed.data.kind) conditions.push(`kind = ${add(parsed.data.kind)}`);
  if (parsed.data.status) conditions.push(`status = ${add(parsed.data.status)}`);
  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  const filterValues = [...values];
  const limit = add(parsed.data.pageSize);
  const offset = add((parsed.data.page - 1) * parsed.data.pageSize);

  try {
    const [data, count] = await Promise.all([
      query<JobListRow>(
        `SELECT id::text, kind, status, created_at, finished_at, retry_count, max_retries
         FROM job
         ${where}
         ORDER BY created_at DESC, id DESC
         LIMIT ${limit} OFFSET ${offset}`,
        values
      ),
      query<{ total: number }>(
        `SELECT COUNT(*)::int AS total FROM job ${where}`,
        filterValues
      )
    ]);
    const total = count.rows[0]?.total ?? 0;
    return json(
      {
        jobs: data.rows.map((row) => ({
          id: row.id,
          kind: row.kind,
          status: row.status,
          createdAt: row.created_at.toISOString(),
          finishedAt: row.finished_at?.toISOString() ?? null,
          retryCount: row.retry_count,
          maxRetries: row.max_retries
        })),
        page: parsed.data.page,
        pageSize: parsed.data.pageSize,
        total,
        totalPages: total === 0 ? 0 : Math.ceil(total / parsed.data.pageSize)
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'jobs');
  }
}
