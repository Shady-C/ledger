import { z } from 'zod';

import {
  currencyCodeSchema,
  decimalStringSchema,
  positiveDecimalStringSchema,
  uuidSchema
} from './primitives.js';

export const accountKindSchema = z.enum(['credit_card', 'chequing', 'savings', 'wallet']);
export const balanceBasisSchema = z.enum(['balance', 'net_activity']);
export const maskedAccountReferenceSchema = z
  .string()
  .trim()
  .min(4)
  .max(64)
  .regex(/^[^\d]+\d{2,6}$/u, 'Use a masked label followed by only the final 2–6 digits');

export const accountSummarySchema = z.object({
  id: uuidSchema,
  displayName: z.string().min(1),
  institutionId: uuidSchema.nullable(),
  institutionName: z.string().min(1).nullable(),
  kind: accountKindSchema,
  nativeCurrency: currencyCodeSchema,
  accountRefMasked: maskedAccountReferenceSchema.nullable(),
  currentBalance: decimalStringSchema,
  currentBalanceBase: decimalStringSchema.nullable(),
  baseCurrency: currencyCodeSchema,
  balanceBasis: balanceBasisSchema,
  lastStatementDate: z.string().nullable(),
  creditLimit: positiveDecimalStringSchema.nullable(),
  usedCredit: decimalStringSchema.nullable(),
  availableCredit: decimalStringSchema.nullable(),
  utilizationPercent: decimalStringSchema.nullable()
});

export const accountsResponseSchema = z.object({
  accounts: z.array(accountSummarySchema),
  creditUtilization: z.object({
    baseCurrency: currencyCodeSchema,
    usedCreditBase: decimalStringSchema,
    creditLimitBase: decimalStringSchema,
    availableCreditBase: decimalStringSchema,
    utilizationPercent: decimalStringSchema.nullable(),
    includedAccountCount: z.number().int().nonnegative(),
    excludedAccounts: z.array(
      z.object({
        accountId: uuidSchema,
        displayName: z.string().min(1),
        reason: z.enum(['missing_credit_limit', 'unverified_balance', 'missing_fx_rate'])
      })
    )
  })
});

const accountWriteFields = {
  institutionId: uuidSchema.nullable().optional(),
  displayName: z.string().trim().min(1).max(120),
  kind: accountKindSchema,
  nativeCurrency: currencyCodeSchema,
  accountRefMasked: maskedAccountReferenceSchema.nullable().optional(),
  creditLimit: positiveDecimalStringSchema.nullable().optional()
};

export const accountCreateSchema = z
  .object(accountWriteFields)
  .strict()
  .superRefine((value, context) => {
    if (value.creditLimit != null && value.kind !== 'credit_card') {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['creditLimit'],
        message: 'Only credit-card accounts can have a credit limit'
      });
    }
  });

export const accountPatchSchema = z
  .object({
    institutionId: accountWriteFields.institutionId,
    displayName: accountWriteFields.displayName.optional(),
    kind: accountWriteFields.kind.optional(),
    nativeCurrency: accountWriteFields.nativeCurrency.optional(),
    accountRefMasked: accountWriteFields.accountRefMasked,
    creditLimit: accountWriteFields.creditLimit
  })
  .strict()
  .refine((value) => Object.keys(value).length > 0, 'At least one account field is required')
  .superRefine((value, context) => {
    if (value.creditLimit != null && value.kind !== undefined && value.kind !== 'credit_card') {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['creditLimit'],
        message: 'Only credit-card accounts can have a credit limit'
      });
    }
  });

export type AccountKind = z.infer<typeof accountKindSchema>;
export type BalanceBasis = z.infer<typeof balanceBasisSchema>;
export type AccountSummary = z.infer<typeof accountSummarySchema>;
export type AccountsResponse = z.infer<typeof accountsResponseSchema>;
export type AccountCreate = z.infer<typeof accountCreateSchema>;
export type AccountPatch = z.infer<typeof accountPatchSchema>;
