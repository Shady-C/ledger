import { z } from 'zod';

import { isoDateSchema, uuidSchema } from './primitives.js';
import { transactionDirectionSchema } from './transaction.js';

const emptyStringToUndefined = (value: unknown) => (value === '' || value === null ? undefined : value);

const optionalDate = z.preprocess(emptyStringToUndefined, isoDateSchema.optional());
const optionalUuid = z.preprocess(emptyStringToUndefined, uuidSchema.optional());
const optionalDirection = z.preprocess(emptyStringToUndefined, transactionDirectionSchema.optional());

export const transactionSortSchema = z.enum([
  'booked_date_desc',
  'booked_date_asc',
  'amount_desc',
  'amount_asc'
]);

export const transactionQuerySchema = z
  .object({
    accountId: optionalUuid,
    categoryId: optionalUuid,
    direction: optionalDirection,
    from: optionalDate,
    to: optionalDate,
    search: z.preprocess(
      emptyStringToUndefined,
      z.string().trim().min(1).max(120).optional()
    ),
    sort: z.preprocess(emptyStringToUndefined, transactionSortSchema.default('booked_date_desc')),
    page: z.preprocess(emptyStringToUndefined, z.coerce.number().int().min(1).default(1)),
    pageSize: z.preprocess(emptyStringToUndefined, z.coerce.number().int().min(1).max(100).default(25))
  })
  .strict()
  .superRefine((query, context) => {
    if (query.from && query.to && query.from > query.to) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: '`from` must be on or before `to`',
        path: ['from']
      });
    }
  });

export const analyticsViewSchema = z.enum(['balance', 'cashflow', 'net-worth', 'fx']);

export const jobQuerySchema = z
  .object({
    kind: z.preprocess(
      emptyStringToUndefined,
      z.enum(['ingest', 'categorize', 'fx_refresh', 'base_currency_rebuild', 'analytics_refresh']).optional()
    ),
    status: z.preprocess(
      emptyStringToUndefined,
      z.enum(['queued', 'claimed', 'done', 'failed', 'needs_ai']).optional()
    ),
    page: z.preprocess(emptyStringToUndefined, z.coerce.number().int().min(1).default(1)),
    pageSize: z.preprocess(
      emptyStringToUndefined,
      z.coerce.number().int().min(1).max(100).default(25)
    )
  })
  .strict();

export const analyticsQuerySchema = z
  .object({
    accountId: optionalUuid,
    from: optionalDate,
    to: optionalDate
  })
  .strict()
  .superRefine((query, context) => {
    if (query.from && query.to && query.from > query.to) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: '`from` must be on or before `to`',
        path: ['from']
      });
    }
  });

export type AnalyticsQuery = z.infer<typeof analyticsQuerySchema>;
export type AnalyticsView = z.infer<typeof analyticsViewSchema>;
export type TransactionQuery = z.infer<typeof transactionQuerySchema>;
export type TransactionSort = z.infer<typeof transactionSortSchema>;
export type JobQuery = z.infer<typeof jobQuerySchema>;
