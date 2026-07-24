import { describe, expect, it } from 'vitest';
import { analyticsQuerySchema, transactionQuerySchema } from '@ledger/shared-types';

import {
  accountsSummarySql,
  buildBalanceQuery,
  buildCashflowQuery,
  buildTransactionQueries
} from './db.js';

describe('accountsSummarySql', () => {
  it('falls back to opening plus all activity when the latest closing is unknown', () => {
    expect(accountsSummarySql).toContain('WHEN latest.closing_balance IS NOT NULL');
    expect(accountsSummarySql).toContain('COALESCE(earliest.opening_balance, 0) + COALESCE(SUM(t.amount_native), 0)');
    expect(accountsSummarySql).toContain('t.booked_date > latest.period_end');
  });
});

describe('buildTransactionQueries', () => {
  it('keeps search text and filters in query parameters', () => {
    const spec = transactionQuerySchema.parse({
      accountId: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
      search: `Cafe%' OR true --`,
      direction: 'debit',
      page: '2',
      pageSize: '10',
      sort: 'amount_desc'
    });
    const built = buildTransactionQueries(spec);

    expect(built.data.text).not.toContain('Cafe');
    expect(built.data.text).toContain('ORDER BY amount_base DESC');
    expect(built.data.values).toEqual([
      'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
      'debit',
      `%Cafe\\%' OR true --%`,
      10,
      10
    ]);
    expect(built.count.values).toHaveLength(3);
  });

  it('adds the earliest statement opening balance before the running sum', () => {
    const built = buildTransactionQueries(transactionQuerySchema.parse({ sort: 'booked_date_asc' }));
    expect(built.data.text).toContain('COALESCE(o.opening_balance, 0) + SUM(t.amount_base)');
    expect(built.data.text).toContain('ORDER BY s.account_id, s.period_start, s.id');
    expect(built.data.text).toContain('ORDER BY booked_date ASC, id ASC');
  });
});

describe('analytics query builders', () => {
  it('parameterizes account and date filters', () => {
    const spec = analyticsQuerySchema.parse({
      accountId: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
      from: '2026-01-01',
      to: '2026-06-30'
    });
    const balance = buildBalanceQuery(spec);
    const cashflow = buildCashflowQuery(spec);

    expect(balance.values).toEqual([
      'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
      '2026-01-01',
      '2026-06-30'
    ]);
    expect(cashflow.values).toEqual(balance.values);
    expect(balance.text).not.toContain('e1bb45a1');
    expect(cashflow.text).not.toContain('2026-01-01');
  });

  it('sums each selected account opening before all dated deltas', () => {
    const built = buildBalanceQuery(analyticsQuerySchema.parse({ from: '2026-04-01' }));
    expect(built.text).toContain('SUM(first_statement.opening_balance)');
    expect(built.text).toContain('(SELECT amount FROM opening)');
    expect(built.text.indexOf('SUM(delta) OVER')).toBeLessThan(built.text.indexOf('WHERE date >='));
  });

  it('classifies credit-card refunds as inflow and charges as outflow', () => {
    const built = buildCashflowQuery(analyticsQuerySchema.parse({}));
    const sql = built.text.replace(/\s+/g, ' ').trim();

    expect(sql).toContain(
      "WHEN a.kind = 'credit_card' AND t.amount_base < 0 AND t.direction IN ('credit', 'refund') THEN ABS(t.amount_base)"
    );
    expect(sql).toContain(
      "WHEN a.kind = 'credit_card' AND t.amount_base > 0 AND t.direction <> 'payment' THEN t.amount_base"
    );
  });

  it('classifies asset-account deposits as inflow and withdrawals as outflow', () => {
    const built = buildCashflowQuery(analyticsQuerySchema.parse({}));
    const sql = built.text.replace(/\s+/g, ' ').trim();

    expect(sql).toContain("JOIN account a ON a.id = t.account_id");
    expect(sql).toContain(
      "WHEN a.kind IN ('chequing', 'savings', 'wallet') AND t.amount_base > 0 THEN t.amount_base"
    );
    expect(sql).toContain(
      "WHEN a.kind IN ('chequing', 'savings', 'wallet') AND t.amount_base < 0 THEN ABS(t.amount_base)"
    );
    expect(sql).toContain(
      '(COALESCE(SUM(inflow), 0) - COALESCE(SUM(outflow), 0))::text AS net'
    );
  });
});
