import { z } from 'zod';

import { balanceBasisSchema } from './account.js';
import { currencyCodeSchema, decimalStringSchema, isoDateSchema } from './primitives.js';

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
  net: decimalStringSchema
});

export const cashflowResponseSchema = z.object({
  currency: currencyCodeSchema,
  points: z.array(cashflowPointSchema)
});

export type BalancePoint = z.infer<typeof balancePointSchema>;
export type BalanceResponse = z.infer<typeof balanceResponseSchema>;
export type CashflowPoint = z.infer<typeof cashflowPointSchema>;
export type CashflowResponse = z.infer<typeof cashflowResponseSchema>;
