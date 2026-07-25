import { describe, expect, it } from 'vitest';

import {
  baseCurrencyRebuildJobResultSchema,
  fxRefreshJobResultSchema,
  workerBaseCurrencyRebuildJobResultSchema,
  workerFxRefreshJobResultSchema,
  workerIngestResultSchema
} from '../src/index.js';

describe('workerIngestResultSchema', () => {
  it('retains every per-file reconciliation value', () => {
    const result = workerIngestResultSchema.parse({
      added: 12,
      skipped: 2,
      files: [
        {
          file_key: 'statements/account/2026-01-01/example.xlsx',
          adapter: 'amex_xlsx',
          status: 'done',
          added: 12,
          skipped: 2,
          statement_id: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
          reconcile: {
            status: 'ok',
            opening_balance: '125.00',
            transaction_total: '2730.59',
            calculated_closing: '2855.59',
            reported_closing: '2855.59',
            difference: '0.00',
            coverage_gaps: [{ start: '2026-02-01', end: '2026-02-28' }]
          },
          reason: null
        }
      ]
    });

    expect(result.files[0]?.reconcile).toEqual({
      status: 'ok',
      opening_balance: '125.00',
      transaction_total: '2730.59',
      calculated_closing: '2855.59',
      reported_closing: '2855.59',
      difference: '0.00',
      coverage_gaps: [{ start: '2026-02-01', end: '2026-02-28' }]
    });
  });

  it('accepts a pending reconciliation with unavailable balances', () => {
    const parsed = workerIngestResultSchema.safeParse({
      added: 0,
      skipped: 0,
      files: [
        {
          file_key: 'statements/example.csv',
          adapter: 'generic_csv',
          status: 'done',
          added: 0,
          skipped: 0,
          statement_id: null,
          reconcile: {
            status: 'pending',
            opening_balance: null,
            transaction_total: '0.00',
            calculated_closing: null,
            reported_closing: null,
            difference: null,
            coverage_gaps: []
          },
          reason: null
        }
      ]
    });
    expect(parsed.success).toBe(true);
  });

  it('accepts a needs-ai file without a reconciliation report', () => {
    const parsed = workerIngestResultSchema.parse({
      added: 4,
      skipped: 0,
      files: [
        {
          file_key: 'statements/unknown.pdf',
          adapter: 'pdf_table',
          status: 'needs_ai',
          added: 0,
          skipped: 0,
          statement_id: null,
          reconcile: null,
          reason: 'No deterministic table was found.'
        }
      ]
    });
    expect(parsed.files[0]?.reconcile).toBeNull();
  });
});

describe('home-currency maintenance results', () => {
  it('rejects unsupported reporting currencies in public and worker results', () => {
    expect(fxRefreshJobResultSchema.safeParse({
      baseCurrency: 'USD',
      quoteCurrencies: [],
      ratesStored: 0,
      transactionsUpdated: 0
    }).success).toBe(false);
    expect(workerFxRefreshJobResultSchema.safeParse({
      base_currency: 'USD',
      quote_currencies: [],
      rates_stored: 0,
      transactions_updated: 0
    }).success).toBe(false);
    expect(baseCurrencyRebuildJobResultSchema.safeParse({
      previousBaseCurrency: 'CAD',
      targetBaseCurrency: 'USD',
      transactionsUpdated: 0,
      settingsUpdated: true
    }).success).toBe(false);
    expect(workerBaseCurrencyRebuildJobResultSchema.safeParse({
      previous_base_currency: 'USD',
      target_base_currency: 'TZS',
      transactions_updated: 0,
      settings_updated: true
    }).success).toBe(false);
  });
});
