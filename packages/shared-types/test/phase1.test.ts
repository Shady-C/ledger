import { describe, expect, it } from 'vitest';

import {
  accountCreateSchema,
  accountsResponseSchema,
  baseCurrencyChangeSchema,
  categorizationProposalSchema,
  jobResponseSchema,
  netWorthResponseSchema,
  settingsPatchSchema,
  transactionCategoryPatchSchema
} from '../src/index.js';

describe('Phase 1 write contracts', () => {
  it('allows an optional positive card limit and rejects limits on asset accounts', () => {
    expect(
      accountCreateSchema.safeParse({
        displayName: 'Travel card',
        kind: 'credit_card',
        nativeCurrency: 'USD',
        marketCode: 'TZ',
        creditLimit: '5000.00'
      }).success
    ).toBe(true);
    expect(
      accountCreateSchema.safeParse({
        displayName: 'Savings',
        kind: 'savings',
        nativeCurrency: 'CAD',
        marketCode: 'CA',
        creditLimit: '5000.00'
      }).success
    ).toBe(false);
    expect(
      accountCreateSchema.safeParse({
        displayName: 'Bad card',
        kind: 'credit_card',
        nativeCurrency: 'USD',
        marketCode: 'TZ',
        creditLimit: '0.00'
      }).success
    ).toBe(false);
  });

  it('accepts only suffix-style masked account references', () => {
    const account = {
      displayName: 'Travel card',
      kind: 'credit_card',
      nativeCurrency: 'USD',
      marketCode: 'TZ'
    } as const;
    expect(accountCreateSchema.safeParse({ ...account, accountRefMasked: '•••• 4242' }).success).toBe(true);
    expect(accountCreateSchema.safeParse({ ...account, accountRefMasked: 'ending 54321' }).success).toBe(true);
    expect(accountCreateSchema.safeParse({ ...account, accountRefMasked: '4111 1111 1111 1111' }).success).toBe(false);
    expect(accountCreateSchema.safeParse({ ...account, accountRefMasked: '4242' }).success).toBe(false);
  });

  it('keeps category correction and base-currency inputs narrow', () => {
    expect(
      transactionCategoryPatchSchema.parse({
        categoryId: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522'
      })
    ).toMatchObject({ applyToMerchant: false });
    expect(baseCurrencyChangeSchema.safeParse({ baseCurrency: 'cad', confirmed: true }).success).toBe(false);
    expect(baseCurrencyChangeSchema.safeParse({ baseCurrency: 'USD', confirmed: true }).success).toBe(false);
    expect(baseCurrencyChangeSchema.safeParse({ baseCurrency: 'TZS' }).success).toBe(false);
    expect(baseCurrencyChangeSchema.safeParse({ baseCurrency: 'TZS', confirmed: true }).success).toBe(true);
    expect(settingsPatchSchema.safeParse({ marketProfile: 'CA' }).success).toBe(true);
    expect(settingsPatchSchema.safeParse({ marketProfile: null }).success).toBe(true);
  });
});

describe('Phase 1 read contracts', () => {
  it('accepts partial net worth with explicit exclusions and exact decimals', () => {
    expect(
      netWorthResponseSchema.safeParse({
        baseCurrency: 'CAD',
        valuationDate: '2026-07-24',
        status: 'partial',
        assets: '100.00',
        liabilities: '25.00',
        netWorth: '75.00',
        accounts: [],
        excludedAccounts: [
          {
            accountId: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
            displayName: 'Unvalued wallet',
            reason: 'missing_fx_rate'
          }
        ]
      }).success
    ).toBe(true);
  });

  it('requires server-computed aggregate credit utilization', () => {
    expect(
      accountsResponseSchema.safeParse({
        accounts: [],
        creditUtilization: {
          baseCurrency: 'CAD',
          usedCreditBase: '250.00',
          creditLimitBase: '1000.00',
          availableCreditBase: '750.00',
          utilizationPercent: '25.00',
          includedAccountCount: 1,
          excludedAccounts: []
        }
      }).success
    ).toBe(true);
  });

  it('requires proposal audit metadata and discriminates job results by kind', () => {
    expect(
      categorizationProposalSchema.safeParse({
        id: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
        opaqueKey: 'c232009a-d652-45d2-82f1-956b998f304b',
        merchantId: '54ccbc13-955e-4104-b7e7-bb0b8c0e4f6d',
        merchantName: 'Corner Cafe',
        flowType: 'spend',
        proposedCategoryId: null,
        proposedCategoryName: 'Coffee',
        proposedCategoryKind: 'spend',
        confidence: '0.7400',
        status: 'pending',
        provider: 'anthropic',
        model: 'claude-haiku-4-5',
        reviewedAt: null,
        createdAt: '2026-07-24T09:00:00.000Z'
      }).success
    ).toBe(true);

    expect(
      jobResponseSchema.safeParse({
        id: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
        kind: 'categorize',
        status: 'done',
        createdAt: '2026-07-24T09:00:00.000Z',
        finishedAt: '2026-07-24T09:00:01.000Z',
        retryCount: 0,
        maxRetries: 3,
        error: null,
        result: { scanned: 4, autoApplied: 2, proposalsCreated: 1, unchanged: 1 }
      }).success
    ).toBe(true);
  });
});
