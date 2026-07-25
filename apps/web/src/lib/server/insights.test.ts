import { describe, expect, it } from 'vitest';
import {
  insightFindingsQuerySchema,
  insightRecurringQuerySchema,
  insightTrendsQuerySchema
} from '@ledger/shared-types';

import {
  buildCoverageQuery,
  buildFindingReviewUpdate,
  buildFindingQueries,
  buildMoversQuery,
  buildRecurringReviewUpdate,
  buildRecurringQueries,
  buildSeasonalityQuery,
  buildSummaryQuery,
  buildTrendsQuery,
  enqueueAnalyticsRefreshInTransaction
} from './insights.js';
import type { PoolClient, QueryResult, QueryResultRow } from 'pg';

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
    expect(summary.values).toEqual(['2026-01-01', '2026-12-01', 'ALL', accountId]);
    expect(seasonality.text).toContain("aggregate.dimension_type = 'category'");
    expect(seasonality.text).toContain("COALESCE(aggregate.spending_base, 0)");
    expect(seasonality.text).toContain("ledger.coverage_status = 'complete'");
    expect(seasonality.text).toContain(
      "ledger.period_start < date_trunc('month', CURRENT_DATE)::date"
    );
    expect(seasonality.values).toEqual([
      '2026-01-01',
      '2026-12-01',
      'ALL',
      categoryId,
      'ALL'
    ]);
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
    expect(movers.values).toEqual(['2026-01-01', '2026-12-01', 'ALL', merchantId]);
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

    expect(trends.values).toEqual(['2026-01-01', '2026-12-01', 'merchant', 'ALL']);
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
    expect(recurring.data.text).toContain('series.last_detected_generation = (');
    expect(recurring.data.text).toContain('published.base_currency = ledger.base_currency');
    expect(recurring.data.values).toEqual([
      '2026-01-01',
      '2026-12-31',
      'ALL',
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
    expect(findings.data.text).toContain('finding.last_detected_generation = (');
    expect(findings.data.text).toContain('published.base_currency = ledger.base_currency');
    expect(findings.data.values).toEqual([
      '2026-01-01',
      '2026-12-31',
      'ALL',
      categoryId,
      'monthly_spike',
      'new',
      'warning',
      5,
      0
    ]);
    expect(findings.count.values).toEqual(findings.data.values.slice(0, -2));
  });

  it('uses the selected market across every materialized Insights dimension', () => {
    const summary = buildSummaryQuery({ market: 'TZ' }, range);
    const trends = buildTrendsQuery(
      insightTrendsQuerySchema.parse({ market: 'TZ', groupBy: 'ledger' }),
      range
    );
    const recurring = buildRecurringQueries(
      insightRecurringQuerySchema.parse({ market: 'TZ' }),
      range
    );
    const findings = buildFindingQueries(
      insightFindingsQuerySchema.parse({ market: 'TZ' }),
      range
    );

    for (const built of [summary, trends, recurring.data, findings.data]) {
      expect(built.text).toContain('market_scope');
      expect(built.values).toContain('TZ');
    }
  });

  it('fences stale account filters against the account current market', () => {
    const summary = buildSummaryQuery({ accountId, market: 'TZ' }, range);
    const trends = buildTrendsQuery(
      insightTrendsQuerySchema.parse({ accountId, market: 'TZ' }),
      range
    );
    const seasonality = buildSeasonalityQuery({ accountId, market: 'TZ' }, range);
    const recurring = buildRecurringQueries(
      insightRecurringQuerySchema.parse({ accountId, market: 'TZ' }),
      range
    );
    const findings = buildFindingQueries(
      insightFindingsQuerySchema.parse({ accountId, market: 'TZ' }),
      range
    );

    for (const built of [summary, trends, recurring.data, findings.data]) {
      expect(built.text).toContain('live_scoped_account');
      expect(built.values).toContain(accountId);
      expect(built.values).toContain('TZ');
    }
    expect(seasonality.text.match(/SELECT 1 FROM account live_scoped_account/g)).toHaveLength(2);
    expect(seasonality.text).toContain('WITH eligible_period AS');
  });

  it('fences review writes to the active-currency published generation', () => {
    const recurring = buildRecurringReviewUpdate(accountId, {
      status: 'confirmed',
      expectedAmount: '25.00'
    });
    const finding = buildFindingReviewUpdate(accountId, { status: 'dismissed' });

    for (const built of [recurring, finding]) {
      expect(built.text).toContain('last_detected_generation = (');
      expect(built.text).toContain('published.base_currency = ledger.base_currency');
      expect(built.text).toContain('RETURNING id::text');
      expect(built.text).not.toContain(accountId);
    }
    expect(recurring.values).toEqual(['confirmed', '25.00', accountId]);
    expect(finding.values).toEqual(['dismissed', accountId]);
  });
});

function result<T extends QueryResultRow>(rows: T[]): QueryResult<T> {
  return {
    command: '',
    rowCount: rows.length,
    oid: 0,
    fields: [],
    rows
  };
}

describe('analytics refresh enqueue', () => {
  it('coalesces when a concurrent producer wins the active-job insert race', async () => {
    const statements: string[] = [];
    const client = {
      async query(text: string) {
        statements.push(text);
        if (text.startsWith('SELECT singleton')) return result([{ singleton: true }]);
        if (text.includes('INSERT INTO job')) return result([]);
        if (text.includes('UPDATE job')) {
          return result([{ id: '11111111-1111-4111-8111-111111111111', status: 'claimed' }]);
        }
        throw new Error(`Unexpected query: ${text}`);
      }
    } as unknown as PoolClient;

    await expect(enqueueAnalyticsRefreshInTransaction(client, 'full')).resolves.toEqual({
      jobId: '11111111-1111-4111-8111-111111111111',
      kind: 'analytics_refresh',
      status: 'claimed'
    });
    expect(statements.some((text) => text.includes('INSERT INTO analytics_run'))).toBe(false);
    expect(statements.find((text) => text.includes('INSERT INTO job'))).toContain('DO NOTHING');
    expect(statements.find((text) => text.includes('UPDATE job'))).toContain('rerun_requested');
  });

  it('creates and attaches a currency-stamped run only after winning the job insert', async () => {
    const statements: string[] = [];
    const jobId = '22222222-2222-4222-8222-222222222222';
    const runId = '33333333-3333-4333-8333-333333333333';
    const client = {
      async query(text: string) {
        statements.push(text);
        if (text.startsWith('SELECT singleton')) return result([{ singleton: true }]);
        if (text.includes('INSERT INTO job')) {
          return result([{ id: jobId, status: 'queued' }]);
        }
        if (text.includes('INSERT INTO analytics_run')) return result([{ id: runId }]);
        if (text.includes('jsonb_build_object')) return result([{ id: jobId }]);
        throw new Error(`Unexpected query: ${text}`);
      }
    } as unknown as PoolClient;

    await expect(enqueueAnalyticsRefreshInTransaction(client, 'incremental')).resolves.toEqual({
      jobId,
      kind: 'analytics_refresh',
      status: 'queued'
    });
    expect(statements.map((text) => text.match(/(?:INSERT INTO|UPDATE) [a-z_]+/)?.[0])).toEqual([
      undefined,
      'INSERT INTO job',
      'INSERT INTO analytics_run',
      'UPDATE job'
    ]);
    expect(statements.find((text) => text.includes('INSERT INTO analytics_run'))).toContain(
      'profile.policy_version'
    );
  });
});
