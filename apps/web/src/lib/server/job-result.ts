import {
  workerAnalyticsRefreshJobResultSchema,
  workerBaseCurrencyRebuildJobResultSchema,
  workerCategorizeJobResultSchema,
  workerFxRefreshJobResultSchema,
  workerIngestResultSchema,
  type JobKind,
  type JobResult,
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

export function mapJobResult(status: JobStatus, raw: unknown): IngestResult | null;
export function mapJobResult(kind: JobKind, status: JobStatus, raw: unknown): JobResult | null;
export function mapJobResult(
  kindOrStatus: JobKind | JobStatus,
  statusOrRaw: JobStatus | unknown,
  optionalRaw?: unknown
): JobResult | null {
  const legacyCall = arguments.length === 2;
  const kind: JobKind = legacyCall ? 'ingest' : (kindOrStatus as JobKind);
  const status: JobStatus = legacyCall ? (kindOrStatus as JobStatus) : (statusOrRaw as JobStatus);
  const raw = legacyCall ? statusOrRaw : optionalRaw;
  if (raw === null || raw === undefined) {
    if (status === 'done' || status === 'needs_ai') {
      throw new JobResultContractError(`A ${status} job must include a result.`);
    }
    return null;
  }

  if (kind === 'ingest') {
    const parsed = workerIngestResultSchema.safeParse(raw);
    if (!parsed.success) {
      throw new JobResultContractError('The worker returned an invalid ingest result.');
    }
    return toPublicResult(parsed.data);
  }

  if (kind === 'categorize') {
    const parsed = workerCategorizeJobResultSchema.safeParse(raw);
    if (!parsed.success) throw new JobResultContractError('The worker returned an invalid categorization result.');
    return {
      scanned: parsed.data.scanned,
      autoApplied: parsed.data.auto_applied,
      proposalsCreated: parsed.data.proposals_created,
      unchanged: parsed.data.unchanged
    };
  }

  if (kind === 'fx_refresh') {
    const parsed = workerFxRefreshJobResultSchema.safeParse(raw);
    if (!parsed.success) throw new JobResultContractError('The worker returned an invalid FX refresh result.');
    return {
      baseCurrency: parsed.data.base_currency,
      quoteCurrencies: parsed.data.quote_currencies,
      ratesStored: parsed.data.rates_stored,
      transactionsUpdated: parsed.data.transactions_updated
    };
  }

  if (kind === 'analytics_refresh') {
    const parsed = workerAnalyticsRefreshJobResultSchema.safeParse(raw);
    if (!parsed.success) throw new JobResultContractError('The worker returned an invalid analytics refresh result.');
    return {
      generation: parsed.data.generation,
      mode: parsed.data.mode,
      sourceWatermark: parsed.data.source_watermark,
      aggregateCount: parsed.data.aggregate_count,
      recurringSeriesCount: parsed.data.recurring_series_count,
      findingCount: parsed.data.finding_count,
      durationMs: parsed.data.duration_ms,
      affectedPeriods: parsed.data.affected_periods
    };
  }

  const parsed = workerBaseCurrencyRebuildJobResultSchema.safeParse(raw);
  if (!parsed.success) throw new JobResultContractError('The worker returned an invalid base-currency rebuild result.');
  return {
    previousBaseCurrency: parsed.data.previous_base_currency,
    targetBaseCurrency: parsed.data.target_base_currency,
    transactionsUpdated: parsed.data.transactions_updated,
    settingsUpdated: parsed.data.settings_updated
  };
}
