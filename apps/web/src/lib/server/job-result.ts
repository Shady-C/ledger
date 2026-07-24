import {
  workerIngestResultSchema,
  type IngestResult,
  type JobStatus,
  type WorkerIngestResult
} from '@ledger/shared-types';

export class JobResultContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'JobResultContractError';
  }
}

function toPublicResult(result: WorkerIngestResult): IngestResult {
  return {
    added: result.added,
    skipped: result.skipped,
    files: result.files.map((file) => ({
      fileKey: file.file_key,
      adapter: file.adapter,
      status: file.status,
      added: file.added,
      skipped: file.skipped,
      statementId: file.statement_id,
      reconciliation: file.reconcile
        ? {
            status: file.reconcile.status,
            openingBalance: file.reconcile.opening_balance,
            transactionTotal: file.reconcile.transaction_total,
            calculatedClosing: file.reconcile.calculated_closing,
            reportedClosing: file.reconcile.reported_closing,
            difference: file.reconcile.difference,
            coverageGaps: file.reconcile.coverage_gaps
          }
        : null,
      reason: file.reason
    }))
  };
}

export function mapJobResult(status: JobStatus, raw: unknown): IngestResult | null {
  if (raw === null || raw === undefined) {
    if (status === 'done' || status === 'needs_ai') {
      throw new JobResultContractError(`A ${status} job must include a result.`);
    }
    return null;
  }

  const parsed = workerIngestResultSchema.safeParse(raw);
  if (!parsed.success) {
    throw new JobResultContractError('The worker returned an invalid ingest result.');
  }
  return toPublicResult(parsed.data);
}
