import { json } from '@sveltejs/kit';
import { uuidSchema } from '@ledger/shared-types';
import { createHash } from 'node:crypto';

import { apiError, unavailableOrInternal } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';
import { storeStatement } from '$lib/server/storage.js';
import { checkUploads } from '$lib/server/upload.js';

type JobRow = { id: string };
type AccountExistsRow = { exists: boolean };

export async function POST({ request }) {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return apiError(400, 'invalid_form', 'Expected a multipart form upload.');
  }

  const account = uuidSchema.safeParse(form.get('accountId'));
  if (!account.success) return apiError(400, 'invalid_account', 'Choose a valid account.');

  try {
    const existing = await query<AccountExistsRow>(
      'SELECT EXISTS (SELECT 1 FROM account WHERE id = $1::uuid) AS exists',
      [account.data]
    );
    if (!existing.rows[0]?.exists) {
      return apiError(404, 'account_not_found', 'That account no longer exists.');
    }
  } catch (error) {
    return unavailableOrInternal(error, 'ingest account check');
  }

  const checked = await checkUploads(form.getAll('files'));
  if (!checked.ok) return apiError(400, 'invalid_file', checked.message);

  const uploadedKeys: string[] = [];
  try {
    for (const file of checked.files) {
      const stored = await storeStatement({
        accountId: account.data,
        fileName: file.name,
        body: file.body
      });
      if (!uploadedKeys.includes(stored.key)) uploadedKeys.push(stored.key);
    }

    const deduplicationKey = `ingest:${createHash('sha256')
      .update(account.data)
      .update('\0')
      .update([...uploadedKeys].sort().join('\0'))
      .digest('hex')}`;
    const result = await query<JobRow>(
      `INSERT INTO job (kind, payload, status, deduplication_key)
       VALUES (
         'ingest',
         jsonb_build_object('file_keys', $1::text[], 'account_id', $2::uuid),
         'queued',
         $3
       )
       ON CONFLICT (kind, deduplication_key)
         WHERE deduplication_key IS NOT NULL
           AND status IN ('queued', 'claimed')
       DO UPDATE SET updated_at = job.updated_at
       RETURNING id`,
      [uploadedKeys, account.data, deduplicationKey]
    );
    const job = result.rows[0];
    if (!job) throw new Error('Job insert did not return an id');

    return json(
      { jobId: job.id, status: 'queued' as const },
      {
        status: 202,
        headers: {
          'cache-control': 'no-store',
          location: `/api/jobs/${job.id}`
        }
      }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'ingest');
  }
}
