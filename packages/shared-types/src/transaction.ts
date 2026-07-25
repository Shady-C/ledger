import { z } from 'zod';

import {
  currencyCodeSchema,
  decimalStringSchema,
  isoDateSchema,
  uuidSchema
} from './primitives.js';
import { categorySourceSchema } from './category.js';

export const conversionIndicatorSchema = z.enum(['fx', 'converted', 'pending']);

export const transactionDirectionSchema = z.enum([
  'debit',
  'credit',
  'payment',
  'fee',
  'refund',
  'interest'
]);

export const transactionEnrichmentSchema = z
  .object({
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
  originalAmount: decimalStringSchema.nullable(),
  originalCurrency: currencyCodeSchema.nullable(),
  amountBase: decimalStringSchema.nullable(),
  currencyBase: currencyCodeSchema,
  fxRate: decimalStringSchema.nullable(),
  fxRateDate: isoDateSchema.nullable(),
  fxFeeAmountNative: decimalStringSchema.nullable(),
  isFxFee: z.boolean(),
  valuationStatus: z.enum(['valued', 'pending_fx']),
  conversionIndicators: z.array(conversionIndicatorSchema).default([]),
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

export const transactionMoneySchema = z.object({
  amount: decimalStringSchema,
  currency: currencyCodeSchema
});

export const transactionConversionEvidenceSchema = z.object({
  indicators: z.array(conversionIndicatorSchema),
  valuationStatus: z.enum(['valued', 'pending_fx']),
  original: transactionMoneySchema.nullable(),
  posted: transactionMoneySchema,
  reporting: transactionMoneySchema.nullable(),
  reportingRate: decimalStringSchema.nullable(),
  reportingRateDate: isoDateSchema.nullable(),
  bankAppliedRate: decimalStringSchema.nullable(),
  referenceRate: decimalStringSchema.nullable(),
  referenceRateDate: isoDateSchema.nullable(),
  referenceRateSource: z.string().min(1).nullable(),
  explicitFeeNative: decimalStringSchema.nullable(),
  explicitFeeBase: decimalStringSchema.nullable(),
  estimatedMarkupNative: decimalStringSchema.nullable(),
  estimatedMarkupBase: decimalStringSchema.nullable(),
  runningBalanceNative: decimalStringSchema,
  runningBalanceBase: decimalStringSchema.nullable()
});

export const transactionDetailResponseSchema = z.object({
  transaction: transactionSchema,
  conversionEvidence: transactionConversionEvidenceSchema
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
export type ConversionIndicator = z.infer<typeof conversionIndicatorSchema>;
export type TransactionMoney = z.infer<typeof transactionMoneySchema>;
export type TransactionDetailResponse = z.infer<typeof transactionDetailResponseSchema>;
export type TransactionDirection = z.infer<typeof transactionDirectionSchema>;
export type TransactionPage = z.infer<typeof transactionPageSchema>;
export type TransactionCategoryPatch = z.infer<typeof transactionCategoryPatchSchema>;
export type TransactionCategoryUpdateResponse = z.infer<typeof transactionCategoryUpdateResponseSchema>;
