import { describe, expect, it } from 'vitest';

import { accountSummarySchema, balanceResponseSchema } from '../src/index.js';

const account = {
  id: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
  displayName: 'Amex Card',
  institutionName: 'American Express',
  kind: 'credit_card',
  nativeCurrency: 'CAD',
  accountRefMasked: '••••1001',
  currentBalance: '129.30',
  lastStatementDate: '2026-07-05'
};

describe('balance basis contracts', () => {
  it('distinguishes verified balances from transaction-only net activity', () => {
    expect(accountSummarySchema.parse({ ...account, balanceBasis: 'net_activity' })).toMatchObject({
      balanceBasis: 'net_activity'
    });
    expect(
      balanceResponseSchema.parse({
        currency: 'CAD',
        basis: 'balance',
        points: [{ date: '2026-07-05', balance: '2855.59' }]
      })
    ).toMatchObject({ basis: 'balance' });
  });

  it('rejects an unspecified or unknown balance basis', () => {
    expect(accountSummarySchema.safeParse(account).success).toBe(false);
    expect(
      balanceResponseSchema.safeParse({ currency: 'CAD', basis: 'estimate', points: [] }).success
    ).toBe(false);
  });
});
