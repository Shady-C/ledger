import { describe, expect, it } from 'vitest';

import {
  insightFindingsQuerySchema,
  insightFindingPatchSchema,
  insightRebuildRequestSchema,
  insightSummaryQuerySchema,
  insightTrendsQuerySchema,
  recurringPatchSchema
} from '../src/index.js';

describe('insights query contracts', () => {
  it('applies stable defaults and coerces pagination', () => {
    const trends = insightTrendsQuerySchema.parse({});
    const findings = insightFindingsQuerySchema.parse({ page: '2', pageSize: '10' });

    expect(trends).toMatchObject({ range: '12m', groupBy: 'ledger' });
    expect(findings).toMatchObject({ range: '12m', page: 2, pageSize: 10 });
  });

  it('rejects reversed date ranges and unsupported query keys', () => {
    expect(
      insightTrendsQuerySchema.safeParse({ from: '2026-06-01', to: '2026-05-01' }).success
    ).toBe(false);
    expect(insightFindingsQuerySchema.safeParse({ surprise: 'true' }).success).toBe(false);
  });

  it('allows combined entity filters on lists but keeps materialized aggregate reads unambiguous', () => {
    const combined = {
      accountId: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
      categoryId: '57e68f0d-846d-4f0e-858b-2838992d2bab'
    };
    expect(insightFindingsQuerySchema.safeParse(combined).success).toBe(true);
    expect(insightSummaryQuerySchema.safeParse(combined).success).toBe(false);
  });

  it('accepts only reviewable finding transitions and non-empty recurring changes', () => {
    expect(insightFindingPatchSchema.parse({ status: 'dismissed' })).toEqual({
      status: 'dismissed'
    });
    expect(insightFindingPatchSchema.safeParse({ status: 'new' }).success).toBe(false);
    expect(recurringPatchSchema.safeParse({}).success).toBe(false);
    expect(recurringPatchSchema.parse({ cadence: 'monthly', expectedAmount: '19.99' })).toEqual({
      cadence: 'monthly',
      expectedAmount: '19.99'
    });
  });

  it('defaults manual rebuilds to full mode', () => {
    expect(insightRebuildRequestSchema.parse({})).toEqual({ mode: 'full' });
  });
});
