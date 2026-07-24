import { describe, expect, it } from 'vitest';
import {
  insightFindingsQuerySchema,
  insightRecurringQuerySchema,
  insightTrendsQuerySchema
} from '@ledger/shared-types';

import {
  buildCoverageQuery,
  buildFindingQueries,
  buildMoversQuery,
  buildRecurringQueries,
  buildSeasonalityQuery,
  buildSummaryQuery,
  buildTrendsQuery
} from './insights.js';

const range = { from: '2026-01-01', to: '2026-12-31' };
const accountId = 'e1bb45a1-04fd-4b64-a95b-f39714e8b522';
const categoryId = '57e68f0d-846d-4f0e-858b-2838992d2bab';
const merchantId = 'bbd9154c-2607-42c3-9ae1-cf7ea414838b';

describe('Insights SQL builders', () => {
  it('reads only the published aggregate generation and parameterizes entity filters', () => {
    const summary = buildSummaryQuery({ accountId }, range);
    const seasonality = buildSeasonalityQuery({ categoryId }, range);

    expect(summary.text).toContain('analytics_monthly_current');
    expect(summary.text).toContain("$1::date - INTERVAL '1 year'");
    expect(summary.text).toContain('SELECT spending_base FROM history');
    expect(summary.text).toContain("aggregate.dimension_type = 'account'");
    expect(summary.text).not.toContain(accountId);
    expect(summary.values).toEqual(['2026-01-01', '2026-12-01', accountId]);
    expect(seasonality.text).toContain("aggregate.dimension_type = 'category'");
    expect(seasonality.text).toContain("COALESCE(aggregate.spending_base, 0)");
    expect(seasonality.text).toContain("ledger.coverage_status = 'complete'");
    expect(seasonality.text).toContain(
      "ledger.period_start < date_trunc('month', CURRENT_DATE)::date"
    );
    expect(seasonality.values).toEqual(['2026-01-01', '2026-12-01', categoryId]);
  });

  it('includes new and disappearing movers while scoping supported entity filters', () => {
    const movers = buildMoversQuery({ merchantId }, range);
    const accountMovers = buildMoversQuery({ accountId }, range);

    expect(movers.text).toContain('FULL OUTER JOIN previous_rows');
    expect(movers.text).toContain("paired.dimension_type = 'merchant'");
    expect(movers.text).toContain(
      "period_start < date_trunc('month', CURRENT_DATE)::date"
    );
    expect(movers.text).not.toContain(merchantId);
    expect(movers.values).toEqual(['2026-01-01', '2026-12-01', merchantId]);
    expect(accountMovers.text).toContain('AND false');
  });

  it('computes coverage from valued and pending native rows with parameterized dates', () => {
    const coverage = buildCoverageQuery({ merchantId }, range);

    expect(coverage.text).toContain('amount_base IS NULL');
    expect(coverage.text).toContain('SUM(amount_native)');
    expect(coverage.text).not.toContain(merchantId);
    expect(coverage.values).toEqual(['2026-01-01', '2026-12-31', merchantId]);
  });

  it('selects requested trend dimensions and calculates trailing robust summaries', () => {
    const spec = insightTrendsQuerySchema.parse({ groupBy: 'merchant', range: '12m' });
    const trends = buildTrendsQuery(spec, range);

    expect(trends.values).toEqual(['2026-01-01', '2026-12-01', 'merchant']);
    expect(trends.text).toContain('PERCENTILE_CONT(0.5)');
    expect(trends.text).toContain("aggregate.dimension_type = $3");
    expect(trends.text).toContain("INTERVAL '2 months'");
    expect(trends.text).toContain("aggregate.period_start - INTERVAL '1 month'");
    expect(trends.text).toContain("aggregate.period_start - INTERVAL '1 year'");
    expect(trends.text).toContain('generate_series');
  });

  it('keeps recurring filters and pagination in bound values', () => {
    const spec = insightRecurringQuerySchema.parse({
      accountId,
      status: 'confirmed',
      cadence: 'monthly',
      page: '2',
      pageSize: '10'
    });
    const recurring = buildRecurringQueries(spec, range);

    expect(recurring.data.text).not.toContain(accountId);
    expect(recurring.data.text).toContain('expected_amount_override');
    expect(recurring.data.values).toEqual([
      '2026-01-01',
      '2026-12-31',
      accountId,
      'confirmed',
      'monthly',
      10,
      10
    ]);
    expect(recurring.count.values).toEqual(recurring.data.values.slice(0, -2));
  });

  it('binds every finding filter and applies a stable severity/status ordering', () => {
    const spec = insightFindingsQuerySchema.parse({
      categoryId,
      type: 'monthly_spike',
      status: 'new',
      severity: 'warning',
      pageSize: '5'
    });
    const findings = buildFindingQueries(spec, range);

    expect(findings.data.text).not.toContain(categoryId);
    expect(findings.data.text).toContain("CASE finding.severity WHEN 'critical'");
    expect(findings.data.text).toContain("finding.evidence ->> 'periodStart'");
    expect(findings.data.values).toEqual([
      '2026-01-01',
      '2026-12-31',
      categoryId,
      'monthly_spike',
      'new',
      'warning',
      5,
      0
    ]);
    expect(findings.count.values).toEqual(findings.data.values.slice(0, -2));
  });
});
