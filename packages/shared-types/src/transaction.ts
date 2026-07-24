import { z } from 'zod';

import {
  currencyCodeSchema,
  decimalStringSchema,
  isoDateSchema,
  uuidSchema
} from './primitives.js';
import { categorySourceSchema } from './category.js';

export const transactionDirectionSchema = z.enum([
  'debit',
  'credit',
  'payment',
  'fee',
  'refund',
  'interest'
]);

export const foreignSpendSchema = z.object({
  amount: decimalStringSchema,
  currency: currencyCodeSchema
});

export const transactionEnrichmentSchema = z
  .object({
    foreign_spend: foreignSpendSchema.optional(),
    flags: z.array(z.string().max(80)).optional()
  })
  .passthrough();

export const transactionSchema = z.object({
  id: uuidSchema,
  accountId: uuidSchema,
  accountName: z.string().min(1),
  bookedDate: isoDateSchema,
  postedDate: isoDateSchema.nullable(),
  description: z.string(),
  merchantName: z.string().nullable(),
  categoryId: uuidSchema.nullable(),
  categoryName: z.string().nullable(),
  categorySource: categorySourceSchema,
  categoryConfidence: decimalStringSchema.nullable(),
  amountNative: decimalStringSchema,
  currencyNative: currencyCodeSchema,
  amountBase: decimalStringSchema,
  currencyBase: currencyCodeSchema,
  fxRate: decimalStringSchema,
  direction: transactionDirectionSchema,
  runningBalance: decimalStringSchema,
  runningBalanceNative: decimalStringSchema,
  runningBalanceBase: decimalStringSchema.nullable(),
  enrichment: transactionEnrichmentSchema
});

export const transactionPageSchema = z.object({
  items: z.array(transactionSchema),
  page: z.number().int().positive(),
  pageSize: z.number().int().positive(),
  total: z.number().int().nonnegative(),
  totalPages: z.number().int().nonnegative()
});

export const transactionCategoryPatchSchema = z
  .object({
    categoryId: uuidSchema,
    applyToMerchant: z.boolean().default(false)
  })
  .strict();

export const transactionCategoryUpdateResponseSchema = z.object({
  transaction: z.object({
    id: uuidSchema,
    categoryId: uuidSchema,
    categoryName: z.string().min(1),
    categorySource: categorySourceSchema,
    categoryConfidence: decimalStringSchema
  }),
  merchantTransactionsUpdated: z.number().int().nonnegative()
});

export type Transaction = z.infer<typeof transactionSchema>;
export type TransactionDirection = z.infer<typeof transactionDirectionSchema>;
export type TransactionPage = z.infer<typeof transactionPageSchema>;
export type TransactionCategoryPatch = z.infer<typeof transactionCategoryPatchSchema>;
export type TransactionCategoryUpdateResponse = z.infer<typeof transactionCategoryUpdateResponseSchema>;
