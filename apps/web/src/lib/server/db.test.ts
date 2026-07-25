import { describe, expect, it } from 'vitest';
import { analyticsQuerySchema, transactionQuerySchema } from '@ledger/shared-types';

import {
  accountsSummarySql,
  buildAccountsSummaryQuery,
  buildBalanceQuery,
  buildCashflowQuery,
  buildCreditUtilizationSummaryQuery,
  buildFxAnalyticsQuery,
  buildNetWorthQuery,
  buildTransactionQueries,
  creditUtilizationSummarySql
} from './db.js';

describe('accountsSummarySql', () => {
  it('falls back to opening plus all activity when the latest closing is unknown', () => {
    expect(accountsSummarySql).toContain('WHEN latest.closing_balance IS NOT NULL');
    expect(accountsSummarySql).toContain('COALESCE(earliest.opening_balance, 0) + COALESCE(activity.total, 0)');
    expect(accountsSummarySql).toContain('COALESCE(t.posted_date, t.booked_date) > latest.period_end');
    expect(accountsSummarySql).toContain('AND s.closing_balance IS NOT NULL');
    expect(accountsSummarySql).toContain("ELSE 'net_activity'");
    expect(accountsSummarySql).toContain('positions.credit_limit - positions.current_balance');
    expect(accountsSummarySql).toContain('GREATEST(positions.current_balance, 0) / positions.credit_limit * 100');
  });

  it('aggregates card utilization in the active base currency without clamping', () => {
    expect(creditUtilizationSummarySql).toContain('GREATEST(current_balance, 0) * fx_rate');
    expect(creditUtilizationSummarySql).toContain('(credit_limit - current_balance) * fx_rate');
    expect(creditUtilizationSummarySql).toContain("WHEN fx_rate IS NULL THEN 'missing_fx_rate'");
    expect(creditUtilizationSummarySql).toContain('as_of >= CURRENT_DATE - 7');
  });

  it('keeps account market scope explicit and parameterized', () => {
    const accounts = buildAccountsSummaryQuery(undefined, 'TZ');
    const utilization = buildCreditUtilizationSummaryQuery('TZ');

    expect(accounts.text).toContain('a.market_code = $1');
    expect(utilization.text).toContain('a.market_code = $1');
    expect(accounts.values).toEqual(['TZ']);
    expect(utilization.values).toEqual(['TZ']);
  });
});

describe('buildTransactionQueries', () => {
  it('keeps search text and filters in query parameters', () => {
    const spec = transactionQuerySchema.parse({
      accountId: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
      market: 'TZ',
      search: `Cafe%' OR true --`,
      direction: 'debit',
      page: '2',
      pageSize: '10',
      sort: 'amount_desc'
    });
    const built = buildTransactionQueries(spec);

    expect(built.data.text).not.toContain('Cafe');
    expect(built.data.text).toContain(
      'ORDER BY ABS(amount_base) DESC NULLS LAST, COALESCE(posted_date, booked_date) DESC'
    );
    expect(built.data.values).toEqual([
      'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
      'TZ',
      'debit',
      `%Cafe\\%' OR true --%`,
      10,
      10
    ]);
    expect(built.count.values).toHaveLength(4);
    expect(built.data.text).toContain('market_code = $2');
  });

  it('sorts amount choices by magnitude and applies the requested page offset', () => {
    const built = buildTransactionQueries(
      transactionQuerySchema.parse({ page: '3', pageSize: '50', sort: 'amount_asc' })
    );

    expect(built.data.text).toContain(
      'ORDER BY ABS(amount_base) ASC NULLS LAST, COALESCE(posted_date, booked_date) DESC'
    );
    expect(built.data.values.slice(-2)).toEqual([50, 100]);
  });

  it('adds the earliest statement opening balance before the running sum', () => {
    const built = buildTransactionQueries(transactionQuerySchema.parse({ sort: 'booked_date_asc' }));
    expect(built.data.text).toContain('COALESCE(o.opening_balance, 0) + SUM(base.amount_native)');
    expect(built.data.text).toContain('o.opening_balance_base + SUM(base.amount_base)');
    expect(built.data.text).toContain('ORDER BY s.account_id, s.period_start, s.id');
    expect(built.data.text).toContain('COALESCE(t.posted_date, t.booked_date) AS effective_date');
    expect(built.data.text).toContain('base.statement_period_start NULLS LAST');
    expect(built.data.text).not.toContain('GROUP BY account_id, effective_date');
    expect(built.data.text).toContain(
      'ORDER BY COALESCE(posted_date, booked_date) ASC, booked_date ASC, id ASC'
    );
  });

  it('uses only reconciled statement balances as running-balance anchors', () => {
    const built = buildTransactionQueries(transactionQuerySchema.parse({}));
    expect(built.data.text).toContain("s.reconcile_status IN ('ok', 'gap', 'pending')");
  });

  it('applies market scope to transaction detail and its FX evidence', () => {
    const transactionId = '57e68f0d-846d-4f0e-858b-2838992d2bab';
    const detail = buildTransactionQueries(
      transactionQuerySchema.parse({ market: 'TZ', pageSize: 1 }),
      transactionId
    );
    const fx = buildFxAnalyticsQuery({ market: 'TZ' }, transactionId);

    expect(detail.data.text).toContain('id = $1::uuid');
    expect(detail.data.text).toContain('market_code = $2');
    expect(detail.data.values).toEqual([transactionId, 'TZ', 1, 0]);
    expect(fx.text).toContain('scoped_account.market_code = $1');
    expect(fx.text).toContain('t.id = $2::uuid');
    expect(fx.values).toEqual(['TZ', transactionId]);
  });
});

describe('analytics query builders', () => {
  it('parameterizes account and date filters', () => {
    const spec = analyticsQuerySchema.parse({
      accountId: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
      market: 'CA',
      from: '2026-01-01',
      to: '2026-06-30'
    });
    const balance = buildBalanceQuery(spec);
    const cashflow = buildCashflowQuery(spec);

    expect(balance.values).toEqual([
      'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
      'CA',
      '2026-01-01',
      '2026-06-30'
    ]);
    expect(cashflow.values).toEqual(balance.values);
    expect(balance.text).toContain('a.market_code = $2');
    expect(cashflow.text).toContain('scoped_account.market_code = $2');
    expect(balance.text).not.toContain('e1bb45a1');
    expect(cashflow.text).not.toContain('2026-01-01');
  });

  it('sums each selected account opening before all dated deltas', () => {
    const built = buildBalanceQuery(analyticsQuerySchema.parse({ from: '2026-04-01' }));
    expect(built.text).toContain("WHEN kind = 'credit_card' THEN -opening_base");
    expect(built.text).toContain('AND NOT has_unreconciled_balance');
    expect(built.text).toContain("reconcile_status = 'mismatch'");
    expect(built.text).toContain('SELECT s.period_start, s.opening_balance');
    expect(built.text).not.toContain('SELECT COALESCE(s.opening_balance, 0)');
    expect(built.text).toContain("ELSE 'net_activity'");
    expect(built.text).toContain('(SELECT amount FROM opening)');
    expect(built.text).toContain('COALESCE(t.posted_date, t.booked_date) AS date');
    expect(built.text).toContain('GROUP BY COALESCE(t.posted_date, t.booked_date)');
    expect(built.text.indexOf('SUM(delta) OVER')).toBeLessThan(built.text.indexOf('AND date >='));
  });

  it('preserves a single card balance while negating cards in consolidated net position', () => {
    const consolidated = buildBalanceQuery(analyticsQuerySchema.parse({}));
    const card = buildBalanceQuery(
      analyticsQuerySchema.parse({ accountId: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522' })
    );

    expect(consolidated.text).toContain("WHEN kind = 'credit_card' THEN -opening_base");
    expect(consolidated.text).toContain(
      "WHEN selected.kind = 'credit_card' THEN -t.amount_base"
    );
    expect(card.text).not.toContain("WHEN kind = 'credit_card' THEN -opening_base");
    expect(card.text).toContain('SUM(opening_base)');
    expect(card.text).toContain('SUM(t.amount_base) AS delta');
  });

  it('does not render a fabricated running balance after a pending CAD valuation', () => {
    const built = buildBalanceQuery(analyticsQuerySchema.parse({}));

    expect(built.text).toContain(
      'COUNT(*) FILTER (WHERE t.amount_base IS NULL) AS pending_fx_count'
    );
    expect(built.text).toContain('SUM(pending_fx_count) OVER');
    expect(built.text).toContain('WHERE balance IS NOT NULL');
  });

  it('excludes unverified or unvalued accounts from net worth without hiding why', () => {
    const built = buildNetWorthQuery();
    expect(built.text).toContain("WHEN NOT verified THEN 'unverified_balance'");
    expect(built.text).toContain("WHEN fx_rate IS NULL THEN 'missing_fx_rate'");
    expect(built.text).toContain("WHEN kind = 'credit_card' THEN -ROUND(native_balance * fx_rate, 2)");
    expect(built.text).toContain('SUM(ABS(LEAST(contribution, 0))) OVER ()');
  });

  it('computes FX costs from first-class evidence and cached historical rates', () => {
    const built = buildFxAnalyticsQuery(analyticsQuerySchema.parse({ from: '2026-01-01' }));
    expect(built.values).toEqual(['2026-01-01']);
    expect(built.text).toContain('t.original_amount IS NOT NULL');
    expect(built.text).toContain('t.fx_fee_amount_native IS NOT NULL');
    expect(built.text).toContain('OR t.amount_base IS NULL');
    expect(built.text).toContain('native_to_base_rate IS NULL');
    expect(built.text).toContain('bank_applied_rate / resolved_market_rate - 1');
    expect(built.text).toContain('ABS(t.amount_native) - COALESCE(t.fx_fee_amount_native, 0)');
    expect(built.text).toContain('as_of >= evidence.booked_date - 7');
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
    expect(sql).toContain(
      "WHEN a.kind = 'credit_card' AND t.direction = 'payment' THEN ABS(t.amount_base)"
    );
    expect(sql).toContain('COALESCE(SUM(card_payments), 0)::text AS card_payments');
  });

  it('classifies asset-account deposits as inflow and withdrawals as outflow', () => {
    const built = buildCashflowQuery(analyticsQuerySchema.parse({}));
    const sql = built.text.replace(/\s+/g, ' ').trim();

    expect(sql).toContain("JOIN account a ON a.id = t.account_id");
    expect(sql).toContain("t.enrichment #>> '{categorization,flow_type}'");
    expect(sql).toContain("WHEN COALESCE(");
    expect(sql).toContain("= 'transfer' THEN 0");
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
