import { z } from 'zod';

import { decimalStringSchema, isoDateSchema, uuidSchema } from './primitives.js';

export const jobStatusSchema = z.enum(['queued', 'claimed', 'done', 'failed', 'needs_ai']);
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

export const jobResponseSchema = z.object({
  id: jobIdSchema,
  status: jobStatusSchema,
  createdAt: z.string().datetime(),
  finishedAt: z.string().datetime().nullable(),
  result: ingestResultSchema.nullable(),
  error: z.string().nullable()
});

export type IngestAccepted = z.infer<typeof ingestAcceptedSchema>;
export type IngestFileResult = z.infer<typeof ingestFileResultSchema>;
export type IngestResult = z.infer<typeof ingestResultSchema>;
export type JobResponse = z.infer<typeof jobResponseSchema>;
export type JobStatus = z.infer<typeof jobStatusSchema>;
export type ReconcileResult = z.infer<typeof reconcileResultSchema>;
export type WorkerIngestResult = z.infer<typeof workerIngestResultSchema>;
