import { z } from 'zod';

import { balanceBasisSchema } from './account.js';
import {
  currencyCodeSchema,
  decimalStringSchema,
  isoDateSchema,
  uuidSchema
} from './primitives.js';
import { accountKindSchema } from './account.js';

export const balancePointSchema = z.object({
  date: isoDateSchema,
  balance: decimalStringSchema
});

export const balanceResponseSchema = z.object({
  currency: currencyCodeSchema,
  basis: balanceBasisSchema,
  points: z.array(balancePointSchema)
});

export const cashflowPointSchema = z.object({
  period: isoDateSchema,
  inflow: decimalStringSchema,
  outflow: decimalStringSchema,
  cardPayments: decimalStringSchema,
  net: decimalStringSchema
});

export const cashflowResponseSchema = z.object({
  currency: currencyCodeSchema,
  points: z.array(cashflowPointSchema)
});

export const netWorthAccountSchema = z.object({
  accountId: uuidSchema,
  displayName: z.string().min(1),
  kind: accountKindSchema,
  nativeBalance: decimalStringSchema,
  nativeCurrency: currencyCodeSchema,
  baseValue: decimalStringSchema,
  contribution: decimalStringSchema,
  fxRate: decimalStringSchema,
  fxRateDate: isoDateSchema
});

export const netWorthExcludedReasonSchema = z.enum(['unverified_balance', 'missing_fx_rate']);

export const netWorthResponseSchema = z.object({
  baseCurrency: currencyCodeSchema,
  valuationDate: isoDateSchema,
  status: z.enum(['complete', 'partial']),
  assets: decimalStringSchema,
  liabilities: decimalStringSchema,
  netWorth: decimalStringSchema,
  accounts: z.array(netWorthAccountSchema),
  excludedAccounts: z.array(
    z.object({
      accountId: uuidSchema,
      displayName: z.string().min(1),
      reason: netWorthExcludedReasonSchema
    })
  )
});

export const fxFeeTransactionSchema = z.object({
  transactionId: uuidSchema,
  accountId: uuidSchema,
  accountName: z.string().min(1),
  bookedDate: isoDateSchema,
  description: z.string(),
  foreignAmount: decimalStringSchema,
  foreignCurrency: currencyCodeSchema,
  chargedAmountNative: decimalStringSchema,
  nativeCurrency: currencyCodeSchema,
  cardAppliedRate: decimalStringSchema,
  marketRate: decimalStringSchema.nullable(),
  marketRateDate: isoDateSchema.nullable(),
  marketRateSource: z.string().min(1).nullable(),
  markupPercent: decimalStringSchema.nullable(),
  estimatedFeeNative: decimalStringSchema.nullable(),
  estimatedFeeBase: decimalStringSchema.nullable()
});

export const fxAnalyticsResponseSchema = z.object({
  baseCurrency: currencyCodeSchema,
  totalEstimatedFeeBase: decimalStringSchema,
  transactions: z.array(fxFeeTransactionSchema)
});

export type BalancePoint = z.infer<typeof balancePointSchema>;
export type BalanceResponse = z.infer<typeof balanceResponseSchema>;
export type CashflowPoint = z.infer<typeof cashflowPointSchema>;
export type CashflowResponse = z.infer<typeof cashflowResponseSchema>;
export type FxAnalyticsResponse = z.infer<typeof fxAnalyticsResponseSchema>;
export type NetWorthResponse = z.infer<typeof netWorthResponseSchema>;
