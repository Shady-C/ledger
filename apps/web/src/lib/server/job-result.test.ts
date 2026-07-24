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

  it('maps typed categorization results without treating them as ingest results', () => {
    expect(
      mapJobResult('categorize', 'done', {
        scanned: 8,
        auto_applied: 5,
        proposals_created: 2,
        unchanged: 1
      })
    ).toEqual({ scanned: 8, autoApplied: 5, proposalsCreated: 2, unchanged: 1 });
  });

  it('maps analytics refresh metadata without losing generation identity', () => {
    expect(
      mapJobResult('analytics_refresh', 'done', {
        generation: 4,
        mode: 'incremental',
        source_watermark: '2026-07-24T10:00:00.123456+00:00',
        aggregate_count: 18,
        recurring_series_count: 3,
        finding_count: 2,
        duration_ms: 45,
        affected_periods: ['2026-07-01']
      })
    ).toEqual({
      generation: 4,
      mode: 'incremental',
      sourceWatermark: '2026-07-24T10:00:00.123456+00:00',
      aggregateCount: 18,
      recurringSeriesCount: 3,
      findingCount: 2,
      durationMs: 45,
      affectedPeriods: ['2026-07-01']
    });
  });

  it('rejects a result whose payload does not match its job kind', () => {
    expect(() =>
      mapJobResult('base_currency_rebuild', 'done', {
        scanned: 1,
        auto_applied: 1,
        proposals_created: 0,
        unchanged: 0
      })
    ).toThrow(JobResultContractError);
  });
});
