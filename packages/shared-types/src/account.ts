import { z } from 'zod';

import { currencyCodeSchema, decimalStringSchema, uuidSchema } from './primitives.js';

export const accountKindSchema = z.enum(['credit_card', 'chequing', 'savings', 'wallet']);
export const balanceBasisSchema = z.enum(['balance', 'net_activity']);

export const accountSummarySchema = z.object({
  id: uuidSchema,
  displayName: z.string().min(1),
  institutionName: z.string().min(1).nullable(),
  kind: accountKindSchema,
  nativeCurrency: currencyCodeSchema,
  accountRefMasked: z.string().min(1).nullable(),
  currentBalance: decimalStringSchema,
  balanceBasis: balanceBasisSchema,
  lastStatementDate: z.string().nullable()
});

export const accountsResponseSchema = z.object({
  accounts: z.array(accountSummarySchema)
});

export type AccountKind = z.infer<typeof accountKindSchema>;
export type BalanceBasis = z.infer<typeof balanceBasisSchema>;
export type AccountSummary = z.infer<typeof accountSummarySchema>;
export type AccountsResponse = z.infer<typeof accountsResponseSchema>;
