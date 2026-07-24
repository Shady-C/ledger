import { z } from 'zod';

import { decimalStringSchema, isoDateSchema, uuidSchema } from './primitives.js';

export const jobStatusSchema = z.enum(['queued', 'claimed', 'done', 'failed', 'needs_ai']);
export const jobKindSchema = z.enum([
  'ingest',
  'categorize',
  'fx_refresh',
  'base_currency_rebuild'
]);
export const jobIdSchema = uuidSchema;

export const reconcileResultSchema = z.object({
  status: z.enum(['ok', 'gap', 'mismatch', 'pending']),
  openingBalance: decimalStringSchema.nullable(),
  transactionTotal: decimalStringSchema,
  calculatedClosing: decimalStringSchema.nullable(),
  reportedClosing: decimalStringSchema.nullable(),
  difference: decimalStringSchema.nullable(),
  coverageGaps: z.array(z.object({ start: isoDateSchema, end: isoDateSchema }))
});

export const workerReconcileResultSchema = z.object({
  status: z.enum(['ok', 'gap', 'mismatch', 'pending']),
  opening_balance: decimalStringSchema.nullable(),
  transaction_total: decimalStringSchema,
  calculated_closing: decimalStringSchema.nullable(),
  reported_closing: decimalStringSchema.nullable(),
  difference: decimalStringSchema.nullable(),
  coverage_gaps: z.array(z.object({ start: isoDateSchema, end: isoDateSchema })).default([])
});

export const workerIngestFileResultSchema = z.object({
  file_key: z.string().min(1).max(1024),
  adapter: z.string().min(1).max(120),
  status: z.string().min(1).max(40),
  added: z.number().int().nonnegative(),
  skipped: z.number().int().nonnegative(),
  statement_id: uuidSchema.nullable(),
  reconcile: z.preprocess(
    (value) =>
      typeof value === 'object' && value !== null && Object.keys(value).length === 0 ? null : value,
    workerReconcileResultSchema.nullable()
  ),
  reason: z.string().max(500).nullable()
});

export const workerIngestResultSchema = z.object({
  added: z.number().int().nonnegative(),
  skipped: z.number().int().nonnegative(),
  files: z.array(workerIngestFileResultSchema)
});

export const ingestFileResultSchema = z.object({
  fileKey: z.string().min(1).max(1024),
  adapter: z.string().min(1).max(120),
  status: z.string().min(1).max(40),
  added: z.number().int().nonnegative(),
  skipped: z.number().int().nonnegative(),
  statementId: uuidSchema.nullable(),
  reconciliation: reconcileResultSchema.nullable(),
  reason: z.string().max(500).nullable()
});

export const ingestResultSchema = z.object({
  added: z.number().int().nonnegative(),
  skipped: z.number().int().nonnegative(),
  files: z.array(ingestFileResultSchema)
});

export const ingestAcceptedSchema = z.object({
  jobId: jobIdSchema,
  status: z.literal('queued')
});

export const jobAcceptedSchema = z.object({
  jobId: jobIdSchema,
  kind: jobKindSchema,
  status: z.enum(['queued', 'claimed'])
});

export const categorizeJobResultSchema = z.object({
  scanned: z.number().int().nonnegative(),
  autoApplied: z.number().int().nonnegative(),
  proposalsCreated: z.number().int().nonnegative(),
  unchanged: z.number().int().nonnegative()
});

export const fxRefreshJobResultSchema = z.object({
  baseCurrency: z.string().regex(/^[A-Z]{3}$/),
  quoteCurrencies: z.array(z.string().regex(/^[A-Z]{3}$/)),
  ratesStored: z.number().int().nonnegative()
});

export const baseCurrencyRebuildJobResultSchema = z.object({
  previousBaseCurrency: z.string().regex(/^[A-Z]{3}$/),
  targetBaseCurrency: z.string().regex(/^[A-Z]{3}$/),
  transactionsUpdated: z.number().int().nonnegative(),
  settingsUpdated: z.boolean()
});

const jobResponseBaseSchema = z.object({
  id: jobIdSchema,
  status: jobStatusSchema,
  createdAt: z.string().datetime(),
  finishedAt: z.string().datetime().nullable(),
  retryCount: z.number().int().nonnegative(),
  maxRetries: z.number().int().nonnegative(),
  error: z.string().nullable()
});

export const jobResponseSchema = z.discriminatedUnion('kind', [
  jobResponseBaseSchema.extend({ kind: z.literal('ingest'), result: ingestResultSchema.nullable() }),
  jobResponseBaseSchema.extend({
    kind: z.literal('categorize'),
    result: categorizeJobResultSchema.nullable()
  }),
  jobResponseBaseSchema.extend({
    kind: z.literal('fx_refresh'),
    result: fxRefreshJobResultSchema.nullable()
  }),
  jobResponseBaseSchema.extend({
    kind: z.literal('base_currency_rebuild'),
    result: baseCurrencyRebuildJobResultSchema.nullable()
  })
]);

export const jobListItemSchema = z.object({
  id: jobIdSchema,
  kind: jobKindSchema,
  status: jobStatusSchema,
  createdAt: z.string().datetime(),
  finishedAt: z.string().datetime().nullable(),
  retryCount: z.number().int().nonnegative(),
  maxRetries: z.number().int().nonnegative()
});

export const jobsResponseSchema = z.object({
  jobs: z.array(jobListItemSchema),
  page: z.number().int().positive(),
  pageSize: z.number().int().positive(),
  total: z.number().int().nonnegative(),
  totalPages: z.number().int().nonnegative()
});

export const workerCategorizeJobResultSchema = z.object({
  scanned: z.number().int().nonnegative(),
  auto_applied: z.number().int().nonnegative(),
  proposals_created: z.number().int().nonnegative(),
  unchanged: z.number().int().nonnegative()
});

export const workerFxRefreshJobResultSchema = z.object({
  base_currency: z.string().regex(/^[A-Z]{3}$/),
  quote_currencies: z.array(z.string().regex(/^[A-Z]{3}$/)),
  rates_stored: z.number().int().nonnegative()
});

export const workerBaseCurrencyRebuildJobResultSchema = z.object({
  previous_base_currency: z.string().regex(/^[A-Z]{3}$/),
  target_base_currency: z.string().regex(/^[A-Z]{3}$/),
  transactions_updated: z.number().int().nonnegative(),
  settings_updated: z.boolean()
});

export type IngestAccepted = z.infer<typeof ingestAcceptedSchema>;
export type JobAccepted = z.infer<typeof jobAcceptedSchema>;
export type IngestFileResult = z.infer<typeof ingestFileResultSchema>;
export type IngestResult = z.infer<typeof ingestResultSchema>;
export type JobResponse = z.infer<typeof jobResponseSchema>;
export type JobStatus = z.infer<typeof jobStatusSchema>;
export type JobKind = z.infer<typeof jobKindSchema>;
export type JobResult = NonNullable<z.infer<typeof jobResponseSchema>['result']>;
export type ReconcileResult = z.infer<typeof reconcileResultSchema>;
export type WorkerIngestResult = z.infer<typeof workerIngestResultSchema>;
