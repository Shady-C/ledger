import { describe, expect, it } from 'vitest';

import { analyticsQuerySchema, transactionQuerySchema } from '../src/index.js';

describe('transactionQuerySchema', () => {
  it('applies bounded pagination defaults', () => {
    expect(transactionQuerySchema.parse({})).toMatchObject({
      page: 1,
      pageSize: 25,
      sort: 'booked_date_desc'
    });
  });

  it('coerces URL query values and rejects excessive page sizes', () => {
    expect(transactionQuerySchema.parse({ page: '2', pageSize: '50' })).toMatchObject({
      page: 2,
      pageSize: 50
    });
    expect(transactionQuerySchema.safeParse({ pageSize: '101' }).success).toBe(false);
  });

  it('rejects unknown keys and backwards date ranges', () => {
    expect(transactionQuerySchema.safeParse({ rawSql: 'drop table txn' }).success).toBe(false);
    expect(
      transactionQuerySchema.safeParse({ from: '2026-02-01', to: '2026-01-01' }).success
    ).toBe(false);
  });

  it('rejects calendar dates that JavaScript would normalize', () => {
    expect(transactionQuerySchema.safeParse({ from: '2026-02-31' }).success).toBe(false);
    expect(transactionQuerySchema.safeParse({ from: '2024-02-29' }).success).toBe(true);
  });
});

describe('analyticsQuerySchema', () => {
  it('accepts a valid account/date filter', () => {
    expect(
      analyticsQuerySchema.safeParse({
        accountId: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
        from: '2026-01-01'
      }).success
    ).toBe(true);
  });
});
