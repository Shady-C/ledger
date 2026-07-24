import { describe, expect, it } from 'vitest';

import { JobResultContractError, mapJobResult } from './job-result.js';

describe('mapJobResult', () => {
  it('preserves a valid per-file reconciliation result', () => {
    const result = mapJobResult('done', {
      added: 1,
      skipped: 0,
      files: [
        {
          file_key: 'statements/account/digest.xlsx',
          adapter: 'amex_xlsx',
          status: 'done',
          added: 1,
          skipped: 0,
          statement_id: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
          reconcile: {
            status: 'gap',
            opening_balance: '10.00',
            transaction_total: '2.00',
            calculated_closing: '12.00',
            reported_closing: '12.00',
            difference: '0.00',
            coverage_gaps: [{ start: '2026-02-01', end: '2026-02-03' }]
          },
          reason: null
        }
      ]
    });

    expect(result?.files[0]?.reconciliation?.coverageGaps).toEqual([
      { start: '2026-02-01', end: '2026-02-03' }
    ]);
  });

  it.each(['done', 'needs_ai'] as const)('rejects a terminal %s job without a result', (status) => {
    expect(() => mapJobResult(status, null)).toThrow(JobResultContractError);
  });

  it('allows a failed job without a result', () => {
    expect(mapJobResult('failed', null)).toBeNull();
  });

  it('rejects malformed non-null results for every status', () => {
    expect(() => mapJobResult('failed', { added: -1 })).toThrow(JobResultContractError);
  });
});
