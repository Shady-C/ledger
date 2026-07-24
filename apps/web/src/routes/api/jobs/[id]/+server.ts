import { json } from '@sveltejs/kit';
import { jobIdSchema, jobStatusSchema } from '@ledger/shared-types';

import { apiError, unavailableOrInternal } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';
import { JobResultContractError, mapJobResult } from '$lib/server/job-result.js';

type JobRow = {
  id: string;
  status: string;
  created_at: Date;
  finished_at: Date | null;
  result: unknown;
  error: string | null;
};

export async function GET({ params }) {
  const id = jobIdSchema.safeParse(params.id);
  if (!id.success) return apiError(400, 'invalid_job', 'The job id is invalid.');

  try {
    const result = await query<JobRow>(
      `SELECT id, status, created_at, finished_at, result, error
       FROM job
       WHERE id = $1::uuid`,
      [id.data]
    );
    const row = result.rows[0];
    if (!row) return apiError(404, 'job_not_found', 'That import job was not found.');

    const status = jobStatusSchema.safeParse(row.status);
    if (!status.success) {
      console.error('[job status] worker contract violation', { jobId: row.id, status: row.status });
      return apiError(500, 'invalid_job_state', 'The import status could not be read.');
    }

    let mappedResult: ReturnType<typeof mapJobResult>;
    try {
      mappedResult = mapJobResult(status.data, row.result);
    } catch (error) {
      if (error instanceof JobResultContractError) {
        console.error('[job status] worker result contract violation', {
          jobId: row.id,
          status: status.data,
          message: error.message
        });
        return apiError(500, 'invalid_job_result', 'The import result could not be read.');
      }
      throw error;
    }
    return json(
      {
        id: row.id,
        status: status.data,
        createdAt: row.created_at.toISOString(),
        finishedAt: row.finished_at?.toISOString() ?? null,
        result: mappedResult,
        error: row.error ? 'The import could not be completed. Check the worker logs for details.' : null
      },
      { headers: { 'cache-control': 'no-store' } }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'job status');
  }
}
