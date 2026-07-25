import type {
  AnalyticsRun,
  InsightCoverage,
  InsightDimension,
  InsightFinding,
  InsightFindingPatch,
  InsightFindingsQuery,
  InsightFindingsResponse,
  InsightRecurringQuery,
  InsightRecurringResponse,
  InsightSeasonalityQuery,
  InsightSeasonalityResponse,
  InsightSettingsPatch,
  InsightSettingsResponse,
  InsightSummaryQuery,
  InsightSummaryResponse,
  InsightTrendsQuery,
  InsightTrendsResponse,
  MarketCode,
  RecurringPatch,
  RecurringSeries
} from '@ledger/shared-types';
import type { PoolClient, QueryResultRow } from 'pg';

import { getPool, query } from './db.js';

type BuiltQuery = { text: string; values: unknown[] };
type EntityFilters = {
  accountId?: string;
  categoryId?: string;
  merchantId?: string;
  market?: MarketCode;
};
type ResolvedRange = { from: string; to: string };

export type InsightReadOptions = {
  /** Locally resolved calendar date used for current-period and overdue semantics. */
  asOfDate?: string;
  /** Published source boundary used when coverage reads live transaction rows. */
  sourceWatermark?: string | null;
};

type CoverageRow = {
  valued_transaction_count: number;
  unvalued_transaction_count: number;
  unvalued_by_currency: unknown;
};

type SummaryRow = {
  inflow: string;
  outflow: string;
  spending: string;
  net_cashflow: string;
  current_spending: string | null;
  previous_spending: string | null;
  previous_present: boolean;
  previous_change: string | null;
  previous_change_percent: string | null;
  year_spending: string | null;
  year_present: boolean;
  year_change: string | null;
  year_change_percent: string | null;
};

type RecurringSummaryRow = {
  active_series: number;
  overdue_series: number;
  expected_monthly_amount: string;
};

type FindingCountsRow = {
  new_count: number;
  confirmed_count: number;
  dismissed_count: number;
  resolved_count: number;
};

type AnalyticsRunRow = {
  id: string;
  mode: 'full' | 'incremental';
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  base_currency: string;
  threshold_policy_version: string;
  source_watermark: Date | string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  started_at: Date | string | null;
  finished_at: Date | string | null;
};

type AnalyticsContextRow = {
  active_currency: string;
  published_currency: string | null;
  threshold_policy_version: string | null;
};

export class AnalyticsRebuildingError extends Error {
  constructor() {
    super('Insights are rebuilding for the active home currency.');
    this.name = 'AnalyticsRebuildingError';
  }
}

async function runQuery<T extends QueryResultRow>(
  client: PoolClient | undefined,
  text: string,
  values: readonly unknown[] = []
) {
  return client ? client.query<T>(text, [...values]) : query<T>(text, values);
}

async function withAnalyticsSnapshot<T>(operation: (client: PoolClient) => Promise<T>) {
  const client = await getPool().connect();
  try {
    await client.query('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY');
    const result = await operation(client);
    await client.query('COMMIT');
    return result;
  } catch (error) {
    await client.query('ROLLBACK').catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

async function readAnalyticsContext(client?: PoolClient) {
  const result = await runQuery<AnalyticsContextRow>(
    client,
    `SELECT
       ledger.base_currency AS active_currency,
       run.base_currency AS published_currency,
       run.threshold_policy_version
     FROM ledger_settings ledger
     LEFT JOIN analytics_settings settings ON settings.singleton
     LEFT JOIN analytics_run run ON run.generation = settings.published_generation
     WHERE ledger.singleton`
  );
  const row = result.rows[0];
  if (!row) throw new Error('Ledger settings row is missing');
  if (!row.published_currency || row.published_currency !== row.active_currency) {
    throw new AnalyticsRebuildingError();
  }
  return {
    baseCurrency: row.active_currency,
    thresholdPolicyVersion: row.threshold_policy_version ?? 'v1'
  };
}

type TrendRow = {
  period: string;
  dimension_type: InsightDimension;
  dimension_id: string | null;
  dimension_name: string;
  inflow: string;
  outflow: string;
  spending: string;
  net_cashflow: string;
  trailing_average_spending: string | null;
  trailing_median_spending: string | null;
  previous_month_spending: string | null;
  month_change: string | null;
  month_change_percent: string | null;
  previous_year_spending: string | null;
  year_change: string | null;
  year_change_percent: string | null;
  coverage_status: 'complete' | 'partial';
  missing_valuation_count: number;
};

type MoverRow = {
  dimension_type: 'category' | 'merchant';
  dimension_id: string;
  dimension_name: string;
  current_amount: string;
  previous_amount: string;
  change_amount: string;
  change_percent: string | null;
};

type SeasonalityRow = {
  month_number: number;
  observation_count: number;
  average_spending: string;
  median_spending: string;
};

type RecurringRow = {
  id: string;
  merchant_id: string | null;
  merchant_name: string;
  account_id: string | null;
  account_name: string | null;
  flow_type: 'spend' | 'income';
  cadence: RecurringSeries['cadence'];
  status: RecurringSeries['status'];
  confidence: string;
  comparison_basis: RecurringSeries['comparisonBasis'];
  expected_amount: string;
  comparison_currency: string;
  occurrence_count: number;
  first_occurrence_date: string;
  latest_occurrence_date: string;
  expected_next_date: string | null;
  overdue: boolean;
  latest_change_percent: string | null;
  user_corrected: boolean;
  occurrences: unknown;
};

type FindingRow = {
  id: string;
  finding_type: InsightFinding['type'];
  status: InsightFinding['status'];
  severity: InsightFinding['severity'];
  headline: string;
  summary: string;
  account_id: string | null;
  account_name: string | null;
  category_id: string | null;
  category_name: string | null;
  merchant_id: string | null;
  merchant_name: string | null;
  recurring_series_id: string | null;
  detector_fingerprint: string;
  evidence: unknown;
  first_seen_at: Date | string;
  last_seen_at: Date | string;
  reviewed_at: Date | string | null;
};

function addValue(values: unknown[], value: unknown, cast = '') {
  values.push(value);
  return `$${values.length}${cast}`;
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function monthStart(value: string) {
  return `${value.slice(0, 7)}-01`;
}

function subtractMonths(value: string, count: number) {
  const [year = 1970, month = 1] = value.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1 - count, 1));
  return date.toISOString().slice(0, 10);
}

function timestamp(value: Date | string | null): string | null {
  if (value === null) return null;
  return value instanceof Date ? value.toISOString() : new Date(value).toISOString();
}

function numberFrom(result: Record<string, unknown> | null, ...keys: string[]) {
  for (const key of keys) {
    const value = result?.[key];
    if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, Math.trunc(value));
    if (typeof value === 'string' && /^\d+$/.test(value)) return Number(value);
  }
  return 0;
}

function stringFrom(result: Record<string, unknown> | null, ...keys: string[]) {
  for (const key of keys) {
    const value = result?.[key];
    if (typeof value === 'string' && value) return value;
  }
  return null;
}

function mapAnalyticsRun(row: AnalyticsRunRow | undefined): AnalyticsRun | null {
  if (!row) return null;
  const startedAt = timestamp(row.started_at);
  const finishedAt = timestamp(row.finished_at);
  const resultDuration = numberFrom(row.result, 'durationMs', 'duration_ms');
  const durationMs = resultDuration > 0
    ? resultDuration
    : startedAt && finishedAt
      ? Math.max(0, new Date(finishedAt).getTime() - new Date(startedAt).getTime())
      : null;
  const affectedPeriods = row.result?.affectedPeriods ?? row.result?.affected_periods;
  return {
    id: row.id,
    status: row.status,
    mode: row.mode,
    baseCurrency: row.base_currency,
    thresholdPolicyVersion: row.threshold_policy_version,
    sourceWatermark: timestamp(row.source_watermark)
      ?? stringFrom(row.result, 'sourceWatermark', 'source_watermark'),
    affectedPeriodCount: Array.isArray(affectedPeriods) ? affectedPeriods.length : 0,
    aggregateCount: numberFrom(row.result, 'aggregateCount', 'aggregate_count'),
    recurringSeriesCount: numberFrom(row.result, 'recurringSeriesCount', 'recurring_series_count'),
    findingCount: numberFrom(row.result, 'findingCount', 'finding_count'),
    startedAt,
    finishedAt,
    durationMs,
    error: row.error
  };
}

const activePublishedGenerationSql = `(
  SELECT settings.published_generation
  FROM analytics_settings settings
  JOIN analytics_run published
    ON published.generation = settings.published_generation
  JOIN ledger_settings ledger ON ledger.singleton
  WHERE settings.singleton
    AND published.status = 'succeeded'
    AND published.base_currency = ledger.base_currency
)`;

function liveAccountMarketPredicate(accountValue: string, marketValue: string) {
  return `EXISTS (
    SELECT 1 FROM account live_scoped_account
    WHERE live_scoped_account.id = ${accountValue}::uuid
      AND live_scoped_account.market_code = ${marketValue}
  )`;
}

function aggregateEntityClause(filters: EntityFilters, values: unknown[], alias = 'aggregate') {
  const marketValue = addValue(values, filters.market ?? 'ALL');
  const scope = `${alias}.market_scope = ${marketValue}`;
  if (filters.accountId) {
    const accountValue = addValue(values, filters.accountId);
    const compatibility = filters.market
      ? ` AND ${liveAccountMarketPredicate(accountValue, marketValue)}`
      : '';
    return `${scope} AND ${alias}.dimension_type = 'account' AND ${alias}.account_id = ${accountValue}::uuid${compatibility}`;
  }
  if (filters.categoryId) {
    return `${scope} AND ${alias}.dimension_type = 'category' AND ${alias}.category_id = ${addValue(values, filters.categoryId)}::uuid`;
  }
  if (filters.merchantId) {
    return `${scope} AND ${alias}.dimension_type = 'merchant' AND ${alias}.merchant_id = ${addValue(values, filters.merchantId)}::uuid`;
  }
  return `${scope} AND ${alias}.dimension_type = 'ledger'`;
}

function effectiveDimension(spec: InsightTrendsQuery): InsightDimension {
  if (spec.accountId) return 'account';
  if (spec.categoryId) return 'category';
  if (spec.merchantId) return 'merchant';
  return spec.groupBy;
}

function transactionEntityClauses(filters: EntityFilters, values: unknown[], alias = 'ledger_txn') {
  const clauses: string[] = [];
  if (filters.accountId) clauses.push(`${alias}.account_id = ${addValue(values, filters.accountId)}::uuid`);
  if (filters.categoryId) clauses.push(`${alias}.category_id = ${addValue(values, filters.categoryId)}::uuid`);
  if (filters.merchantId) clauses.push(`${alias}.merchant_id = ${addValue(values, filters.merchantId)}::uuid`);
  if (filters.market) {
    clauses.push(`EXISTS (
      SELECT 1 FROM account scoped_account
      WHERE scoped_account.id = ${alias}.account_id
        AND scoped_account.market_code = ${addValue(values, filters.market)}
    )`);
  }
  return clauses;
}

export async function resolveInsightRange(
  spec: { range: '3m' | '6m' | '12m' | '24m' | 'all'; from?: string; to?: string } & EntityFilters,
  client?: PoolClient
): Promise<ResolvedRange> {
  const to = spec.to ?? today();
  if (spec.from) return { from: spec.from, to };
  if (spec.range !== 'all') {
    const months = { '3m': 3, '6m': 6, '12m': 12, '24m': 24 }[spec.range];
    return { from: subtractMonths(monthStart(to), months - 1), to };
  }
  const values: unknown[] = [];
  const clauses = transactionEntityClauses(spec, values, 'txn');
  const result = await runQuery<{ from_date: string }>(
    client,
    `SELECT COALESCE(MIN(txn.booked_date), $${values.length + 1}::date)::text AS from_date
     FROM txn
     ${clauses.length ? `WHERE ${clauses.join(' AND ')}` : ''}`,
    [...values, to]
  );
  return { from: result.rows[0]?.from_date ?? to, to };
}

export function buildCoverageQuery(
  filters: EntityFilters,
  range: ResolvedRange,
  sourceWatermark?: string | null
): BuiltQuery {
  const values: unknown[] = [];
  const from = addValue(values, range.from, '::date');
  const to = addValue(values, range.to, '::date');
  const entityClauses = transactionEntityClauses(filters, values, 'ledger_txn');
  if (sourceWatermark) {
    entityClauses.push(
      `ledger_txn.updated_at <= ${addValue(values, sourceWatermark, '::timestamptz')}`
    );
  }
  return {
    text: `
      WITH selected AS (
        SELECT ledger_txn.amount_native, ledger_txn.currency_native, ledger_txn.amount_base
        FROM txn ledger_txn
        WHERE ledger_txn.booked_date BETWEEN ${from} AND ${to}
          ${entityClauses.length ? `AND ${entityClauses.join(' AND ')}` : ''}
      ), pending_currency AS (
        SELECT
          currency_native AS currency,
          COUNT(*)::int AS transaction_count,
          COALESCE(SUM(amount_native), 0)::text AS amount_native
        FROM selected
        WHERE amount_base IS NULL
        GROUP BY currency_native
      )
      SELECT
        (COUNT(*) FILTER (WHERE amount_base IS NOT NULL))::int AS valued_transaction_count,
        (COUNT(*) FILTER (WHERE amount_base IS NULL))::int AS unvalued_transaction_count,
        COALESCE(
          (SELECT jsonb_agg(jsonb_build_object(
            'currency', currency,
            'transactionCount', transaction_count,
            'amountNative', amount_native
          ) ORDER BY currency) FROM pending_currency),
          '[]'::jsonb
        ) AS unvalued_by_currency
      FROM selected`,
    values
  };
}

function parseJsonArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    try {
      const parsed: unknown = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

export async function readInsightCoverage(
  filters: EntityFilters,
  range: ResolvedRange,
  client?: PoolClient,
  sourceWatermark?: string | null
): Promise<InsightCoverage> {
  const built = buildCoverageQuery(filters, range, sourceWatermark);
  const result = await runQuery<CoverageRow>(client, built.text, built.values);
  const row = result.rows[0];
  const unvaluedByCurrency = parseJsonArray(row?.unvalued_by_currency).flatMap((value) => {
    if (!value || typeof value !== 'object') return [];
    const item = value as Record<string, unknown>;
    if (typeof item.currency !== 'string') return [];
    return [{
      currency: item.currency,
      transactionCount: Number(item.transactionCount ?? 0),
      amountNative: typeof item.amountNative === 'string' ? item.amountNative : String(item.amountNative ?? '0')
    }];
  });
  const pending = Number(row?.unvalued_transaction_count ?? 0);
  return {
    status: pending > 0 ? 'partial' : 'complete',
    valuedTransactionCount: Number(row?.valued_transaction_count ?? 0),
    unvaluedTransactionCount: pending,
    unvaluedByCurrency
  };
}

export function buildSummaryQuery(filters: EntityFilters, range: ResolvedRange): BuiltQuery {
  const values: unknown[] = [];
  const from = addValue(values, monthStart(range.from), '::date');
  const to = addValue(values, monthStart(range.to), '::date');
  const entityClause = aggregateEntityClause(filters, values);
  return {
    text: `
      WITH history AS (
        SELECT aggregate.*
        FROM analytics_monthly_current aggregate
        WHERE aggregate.period_start BETWEEN ${from} - INTERVAL '1 year' AND ${to}
          AND ${entityClause}
      ), selected AS (
        SELECT * FROM history WHERE period_start BETWEEN ${from} AND ${to}
      ), latest AS (
        SELECT MAX(period_start) AS period_start FROM selected
      ), compared AS (
        SELECT
          COALESCE((SELECT spending_base FROM selected WHERE period_start = latest.period_start), 0) AS current_spending,
          (SELECT spending_base FROM history WHERE period_start = latest.period_start - INTERVAL '1 month') AS previous_spending,
          (SELECT spending_base FROM history WHERE period_start = latest.period_start - INTERVAL '1 year') AS year_spending
        FROM latest
      )
      SELECT
        COALESCE(SUM(selected.inflow_base), 0)::text AS inflow,
        COALESCE(SUM(selected.outflow_base), 0)::text AS outflow,
        COALESCE(SUM(selected.spending_base), 0)::text AS spending,
        COALESCE(SUM(selected.net_base), 0)::text AS net_cashflow,
        compared.current_spending::text,
        compared.previous_spending::text,
        (compared.previous_spending IS NOT NULL) AS previous_present,
        CASE WHEN compared.previous_spending IS NOT NULL
          THEN ROUND(compared.current_spending - compared.previous_spending, 2)::text END AS previous_change,
        CASE WHEN compared.previous_spending <> 0
          THEN ROUND((compared.current_spending - compared.previous_spending) / ABS(compared.previous_spending) * 100, 2)::text END AS previous_change_percent,
        compared.year_spending::text,
        (compared.year_spending IS NOT NULL) AS year_present,
        CASE WHEN compared.year_spending IS NOT NULL
          THEN ROUND(compared.current_spending - compared.year_spending, 2)::text END AS year_change,
        CASE WHEN compared.year_spending <> 0
          THEN ROUND((compared.current_spending - compared.year_spending) / ABS(compared.year_spending) * 100, 2)::text END AS year_change_percent
      FROM compared
      LEFT JOIN selected ON true
      GROUP BY compared.current_spending, compared.previous_spending, compared.year_spending`,
    values
  };
}

function recurringFilterClauses(filters: EntityFilters, range: ResolvedRange, values: unknown[]) {
  const from = addValue(values, range.from, '::date');
  const to = addValue(values, range.to, '::date');
  const occurrenceClauses = [
    `occurrence.series_id = series.id`,
    `occurrence.occurrence_date BETWEEN ${from} AND ${to}`
  ];
  const scope = addValue(values, filters.market ?? 'ALL');
  let liveAccountCompatibility = '';
  if (filters.accountId) {
    const account = addValue(values, filters.accountId);
    occurrenceClauses.push(`EXISTS (
      SELECT 1 FROM txn filtered_transaction
      WHERE filtered_transaction.id = occurrence.transaction_id
        AND filtered_transaction.account_id = ${account}::uuid
    )`);
    if (filters.market) {
      liveAccountCompatibility = `
    AND ${liveAccountMarketPredicate(account, scope)}`;
    }
  }
  if (filters.categoryId) {
    const category = addValue(values, filters.categoryId);
    occurrenceClauses.push(`EXISTS (
      SELECT 1 FROM txn filtered_transaction
      WHERE filtered_transaction.id = occurrence.transaction_id
        AND filtered_transaction.category_id = ${category}::uuid
    )`);
  }
  if (filters.merchantId) {
    const merchant = addValue(values, filters.merchantId);
    occurrenceClauses.push(`series.merchant_id = ${merchant}::uuid`);
  }
  return `series.market_scope = ${scope}
    AND series.last_detected_generation = ${activePublishedGenerationSql}
    ${liveAccountCompatibility}
    AND EXISTS (SELECT 1 FROM recurring_occurrence occurrence WHERE ${occurrenceClauses.join(' AND ')})`;
}

async function readRecurringSummary(
  filters: EntityFilters,
  range: ResolvedRange,
  baseCurrency: string,
  client?: PoolClient
) {
  const values: unknown[] = [];
  const filter = recurringFilterClauses(filters, range, values);
  const result = await runQuery<RecurringSummaryRow>(
    client,
    `SELECT
       (COUNT(*) FILTER (WHERE series.status IN ('detected', 'confirmed')))::int AS active_series,
       (COUNT(*) FILTER (
         WHERE series.status IN ('detected', 'confirmed')
           AND COALESCE(series.next_date_override, series.detected_next_date) < CURRENT_DATE
       ))::int AS overdue_series,
       COALESCE(ROUND(SUM(
         CASE COALESCE(series.cadence_override, series.detected_cadence)
           WHEN 'weekly' THEN COALESCE(series.expected_amount_override, series.detected_expected_amount) * 52 / 12
           WHEN 'biweekly' THEN COALESCE(series.expected_amount_override, series.detected_expected_amount) * 26 / 12
           WHEN 'monthly' THEN COALESCE(series.expected_amount_override, series.detected_expected_amount)
           WHEN 'quarterly' THEN COALESCE(series.expected_amount_override, series.detected_expected_amount) / 3
           WHEN 'annual' THEN COALESCE(series.expected_amount_override, series.detected_expected_amount) / 12
         END
       ) FILTER (
         WHERE series.status IN ('detected', 'confirmed')
           AND series.comparison_currency = ${addValue(values, baseCurrency)}
       ), 2), 0)::text AS expected_monthly_amount
     FROM recurring_series series
     WHERE ${filter}`,
    values
  );
  return result.rows[0] ?? { active_series: 0, overdue_series: 0, expected_monthly_amount: '0' };
}

const evidenceDimensionUuid = `
  finding.evidence ->> 'dimensionId' ~
    '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$'`;
const findingCategoryId = `COALESCE(
  ledger_txn.category_id,
  CASE
    WHEN finding.evidence ->> 'dimensionType' = 'category' AND ${evidenceDimensionUuid}
      THEN (finding.evidence ->> 'dimensionId')::uuid
  END
)`;
const findingMerchantId = `COALESCE(
  ledger_txn.merchant_id,
  series.merchant_id,
  CASE
    WHEN finding.evidence ->> 'dimensionType' = 'merchant' AND ${evidenceDimensionUuid}
      THEN (finding.evidence ->> 'dimensionId')::uuid
  END
)`;
const findingEvidenceDate = `CASE
  WHEN finding.evidence ->> 'periodStart' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    THEN (finding.evidence ->> 'periodStart')::date
  WHEN finding.evidence ->> 'gapStart' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    THEN (finding.evidence ->> 'gapStart')::date
  WHEN finding.evidence ->> 'secondBookedDate' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    THEN (finding.evidence ->> 'secondBookedDate')::date
END`;
const findingEventDate = `COALESCE(
  ledger_txn.booked_date,
  ${findingEvidenceDate},
  (
    SELECT MAX(occurrence.occurrence_date)
    FROM recurring_occurrence occurrence
    WHERE occurrence.series_id = finding.recurring_series_id
  ),
  finding.last_seen_at::date
)`;

function findingEntityClauses(filters: EntityFilters, values: unknown[]) {
  const marketValue = addValue(values, filters.market ?? 'ALL');
  const clauses: string[] = [
    `finding.market_scope = ${marketValue}`,
    `finding.last_detected_generation = ${activePublishedGenerationSql}`
  ];
  if (filters.accountId) {
    const accountValue = addValue(values, filters.accountId);
    clauses.push(`COALESCE(finding.account_id, ledger_txn.account_id) = ${accountValue}::uuid`);
    if (filters.market) {
      clauses.push(liveAccountMarketPredicate(accountValue, marketValue));
    }
  }
  if (filters.categoryId) {
    clauses.push(`${findingCategoryId} = ${addValue(values, filters.categoryId)}::uuid`);
  }
  if (filters.merchantId) {
    clauses.push(`${findingMerchantId} = ${addValue(values, filters.merchantId)}::uuid`);
  }
  return clauses;
}

async function readFindingCounts(filters: EntityFilters, range: ResolvedRange, client?: PoolClient) {
  const values: unknown[] = [];
  const from = addValue(values, range.from, '::date');
  const to = addValue(values, range.to, '::date');
  const entity = findingEntityClauses(filters, values);
  const result = await runQuery<FindingCountsRow>(
    client,
    `SELECT
       (COUNT(*) FILTER (WHERE finding.status = 'new'))::int AS new_count,
       (COUNT(*) FILTER (WHERE finding.status = 'confirmed'))::int AS confirmed_count,
       (COUNT(*) FILTER (WHERE finding.status = 'dismissed'))::int AS dismissed_count,
       (COUNT(*) FILTER (WHERE finding.status = 'resolved'))::int AS resolved_count
     FROM insight_finding finding
     LEFT JOIN txn ledger_txn ON ledger_txn.id = finding.transaction_id
     LEFT JOIN recurring_series series ON series.id = finding.recurring_series_id
     WHERE ${findingEventDate} BETWEEN ${from} AND ${to}
       ${entity.length ? `AND ${entity.join(' AND ')}` : ''}`,
    values
  );
  return result.rows[0] ?? { new_count: 0, confirmed_count: 0, dismissed_count: 0, resolved_count: 0 };
}

async function readLatestRun(baseCurrency: string, client?: PoolClient) {
  const result = await runQuery<AnalyticsRunRow>(
    client,
    `SELECT id::text, mode, status, base_currency, threshold_policy_version,
            source_watermark, result, error, started_at, finished_at
     FROM analytics_run
     WHERE base_currency = $1
     ORDER BY requested_at DESC, id DESC
     LIMIT 1`,
    [baseCurrency]
  );
  return mapAnalyticsRun(result.rows[0]);
}

function comparison(
  current: string | null,
  previous: string | null,
  present: boolean,
  change: string | null,
  changePercent: string | null
) {
  if (!present || previous === null) return null;
  return {
    current: current ?? '0',
    previous,
    change: change ?? '0',
    changePercent
  };
}

export async function readInsightSummary(
  spec: InsightSummaryQuery,
  client?: PoolClient
): Promise<InsightSummaryResponse> {
  if (!client) return withAnalyticsSnapshot((snapshot) => readInsightSummary(spec, snapshot));
  const context = await readAnalyticsContext(client);
  const range = await resolveInsightRange(spec, client);
  const built = buildSummaryQuery(spec, range);
  const [summaryResult, coverage, recurring, findings, latestRun] = await Promise.all([
    runQuery<SummaryRow>(client, built.text, built.values),
    readInsightCoverage(spec, range, client),
    readRecurringSummary(spec, range, context.baseCurrency, client),
    readFindingCounts(spec, range, client),
    readLatestRun(context.baseCurrency, client)
  ]);
  const row = summaryResult.rows[0];
  return {
    baseCurrency: context.baseCurrency,
    range,
    coverage,
    totals: {
      inflow: row?.inflow ?? '0',
      outflow: row?.outflow ?? '0',
      spending: row?.spending ?? '0',
      netCashflow: row?.net_cashflow ?? '0'
    },
    spendingMonthOverMonth: row
      ? comparison(row.current_spending, row.previous_spending, row.previous_present, row.previous_change, row.previous_change_percent)
      : null,
    spendingYearOverYear: row
      ? comparison(row.current_spending, row.year_spending, row.year_present, row.year_change, row.year_change_percent)
      : null,
    recurring: {
      activeSeries: Number(recurring.active_series),
      overdueSeries: Number(recurring.overdue_series),
      expectedMonthlyAmount: recurring.expected_monthly_amount
    },
    findings: {
      new: Number(findings.new_count),
      confirmed: Number(findings.confirmed_count),
      dismissed: Number(findings.dismissed_count),
      resolved: Number(findings.resolved_count),
      unread: Number(findings.new_count)
    },
    latestRun
  };
}

export function buildTrendsQuery(spec: InsightTrendsQuery, range: ResolvedRange): BuiltQuery {
  const values: unknown[] = [];
  const from = addValue(values, monthStart(range.from), '::date');
  const to = addValue(values, monthStart(range.to), '::date');
  let dimension = effectiveDimension(spec);
  let dimensionId: string | undefined;
  if (spec.accountId) { dimension = 'account'; dimensionId = spec.accountId; }
  if (spec.categoryId) { dimension = 'category'; dimensionId = spec.categoryId; }
  if (spec.merchantId) { dimension = 'merchant'; dimensionId = spec.merchantId; }
  const dimensionValue = addValue(values, dimension);
  const marketScope = addValue(values, spec.market ?? 'ALL');
  let dimensionFilter = '';
  if (dimensionId) {
    const dimensionIdValue = addValue(values, dimensionId);
    dimensionFilter = `AND COALESCE(aggregate.account_id, aggregate.category_id, aggregate.merchant_id) = ${dimensionIdValue}::uuid`;
    if (spec.accountId && spec.market) {
      dimensionFilter += ` AND ${liveAccountMarketPredicate(dimensionIdValue, marketScope)}`;
    }
  }
  return {
    text: `
      SELECT
        aggregate.period_start::text AS period,
        aggregate.dimension_type,
        COALESCE(aggregate.account_id, aggregate.category_id, aggregate.merchant_id)::text AS dimension_id,
        COALESCE(account.display_name, category.name, merchant.canonical_name, 'Ledger') AS dimension_name,
        aggregate.inflow_base::text AS inflow,
        aggregate.outflow_base::text AS outflow,
        aggregate.spending_base::text AS spending,
        aggregate.net_base::text AS net_cashflow,
        trailing_stats.average_spending::text AS trailing_average_spending,
        trailing_stats.median_spending::text AS trailing_median_spending,
        previous_month.spending_base::text AS previous_month_spending,
        CASE WHEN previous_month.spending_base IS NOT NULL
          THEN ROUND(aggregate.spending_base - previous_month.spending_base, 2)::text
        END AS month_change,
        CASE WHEN previous_month.spending_base <> 0
          THEN ROUND(
            (aggregate.spending_base - previous_month.spending_base)
              / ABS(previous_month.spending_base) * 100,
            2
          )::text
        END AS month_change_percent,
        previous_year.spending_base::text AS previous_year_spending,
        CASE WHEN previous_year.spending_base IS NOT NULL
          THEN ROUND(aggregate.spending_base - previous_year.spending_base, 2)::text
        END AS year_change,
        CASE WHEN previous_year.spending_base <> 0
          THEN ROUND(
            (aggregate.spending_base - previous_year.spending_base)
              / ABS(previous_year.spending_base) * 100,
            2
          )::text
        END AS year_change_percent,
        aggregate.coverage_status,
        aggregate.pending_fx_count AS missing_valuation_count
      FROM analytics_monthly_current aggregate
      LEFT JOIN account ON account.id = aggregate.account_id
      LEFT JOIN category ON category.id = aggregate.category_id
      LEFT JOIN merchant ON merchant.id = aggregate.merchant_id
      LEFT JOIN analytics_monthly_current previous_month
        ON previous_month.period_start = aggregate.period_start - INTERVAL '1 month'
       AND previous_month.dimension_type = aggregate.dimension_type
       AND previous_month.account_id IS NOT DISTINCT FROM aggregate.account_id
       AND previous_month.category_id IS NOT DISTINCT FROM aggregate.category_id
       AND previous_month.merchant_id IS NOT DISTINCT FROM aggregate.merchant_id
       AND previous_month.market_scope = aggregate.market_scope
      LEFT JOIN analytics_monthly_current previous_year
        ON previous_year.period_start = aggregate.period_start - INTERVAL '1 year'
       AND previous_year.dimension_type = aggregate.dimension_type
       AND previous_year.account_id IS NOT DISTINCT FROM aggregate.account_id
       AND previous_year.category_id IS NOT DISTINCT FROM aggregate.category_id
       AND previous_year.merchant_id IS NOT DISTINCT FROM aggregate.merchant_id
       AND previous_year.market_scope = aggregate.market_scope
      LEFT JOIN LATERAL (
        WITH calendar_month AS (
          SELECT generate_series(
            aggregate.period_start - INTERVAL '2 months',
            aggregate.period_start,
            INTERVAL '1 month'
          )::date AS period_start
        )
        SELECT
          ROUND(AVG(COALESCE(history.spending_base, 0)), 2) AS average_spending,
          ROUND(
            PERCENTILE_CONT(0.5) WITHIN GROUP (
              ORDER BY COALESCE(history.spending_base, 0)
            )::numeric,
            2
          ) AS median_spending
        FROM calendar_month
        LEFT JOIN analytics_monthly_current history
          ON history.period_start = calendar_month.period_start
         AND history.dimension_type = aggregate.dimension_type
         AND history.account_id IS NOT DISTINCT FROM aggregate.account_id
         AND history.category_id IS NOT DISTINCT FROM aggregate.category_id
         AND history.merchant_id IS NOT DISTINCT FROM aggregate.merchant_id
         AND history.market_scope = aggregate.market_scope
        WHERE history.coverage_status IS NULL OR history.coverage_status = 'complete'
      ) trailing_stats ON true
      WHERE aggregate.period_start BETWEEN ${from} AND ${to}
        AND aggregate.dimension_type = ${dimensionValue}
        AND aggregate.market_scope = ${marketScope}
        ${dimensionFilter}
      ORDER BY aggregate.period_start, dimension_name, dimension_id NULLS FIRST`,
    values
  };
}

export function buildMoversQuery(filters: EntityFilters, range: ResolvedRange): BuiltQuery {
  const values: unknown[] = [];
  const from = addValue(values, monthStart(range.from), '::date');
  const to = addValue(values, monthStart(range.to), '::date');
  const marketScope = addValue(values, filters.market ?? 'ALL');
  let entityClause = 'true';
  if (filters.accountId) entityClause = 'false';
  if (filters.categoryId) {
    entityClause = `paired.dimension_type = 'category' AND paired.category_id = ${addValue(values, filters.categoryId)}::uuid`;
  }
  if (filters.merchantId) {
    entityClause = `paired.dimension_type = 'merchant' AND paired.merchant_id = ${addValue(values, filters.merchantId)}::uuid`;
  }
  return {
    text: `
      WITH complete_periods AS (
        SELECT period_start
        FROM analytics_monthly_current
        WHERE dimension_type = 'ledger'
          AND market_scope = ${marketScope}
          AND coverage_status = 'complete'
          AND period_start < date_trunc('month', CURRENT_DATE)::date
          AND period_start BETWEEN ${from} AND ${to}
        ORDER BY period_start DESC
        LIMIT 2
      ), bounds AS (
        SELECT MAX(period_start) AS current_period, MIN(period_start) AS previous_period
        FROM complete_periods
        HAVING COUNT(*) = 2
      ), current_rows AS (
        SELECT aggregate.*
        FROM analytics_monthly_current aggregate
        JOIN bounds ON bounds.current_period = aggregate.period_start
        WHERE aggregate.dimension_type IN ('category', 'merchant')
          AND aggregate.market_scope = ${marketScope}
          AND aggregate.coverage_status = 'complete'
      ), previous_rows AS (
        SELECT aggregate.*
        FROM analytics_monthly_current aggregate
        JOIN bounds ON bounds.previous_period = aggregate.period_start
        WHERE aggregate.dimension_type IN ('category', 'merchant')
          AND aggregate.market_scope = ${marketScope}
          AND aggregate.coverage_status = 'complete'
      ), paired AS (
        SELECT
          COALESCE(current_row.dimension_type, previous_row.dimension_type) AS dimension_type,
          COALESCE(current_row.category_id, previous_row.category_id) AS category_id,
          COALESCE(current_row.merchant_id, previous_row.merchant_id) AS merchant_id,
          COALESCE(current_row.spending_base, 0) AS current_amount,
          COALESCE(previous_row.spending_base, 0) AS previous_amount
        FROM current_rows current_row
        FULL OUTER JOIN previous_rows previous_row
          ON previous_row.dimension_type = current_row.dimension_type
         AND previous_row.category_id IS NOT DISTINCT FROM current_row.category_id
         AND previous_row.merchant_id IS NOT DISTINCT FROM current_row.merchant_id
      )
      SELECT
        paired.dimension_type,
        COALESCE(paired.category_id, paired.merchant_id)::text AS dimension_id,
        COALESCE(category.name, merchant.canonical_name) AS dimension_name,
        paired.current_amount::text,
        paired.previous_amount::text,
        ROUND(paired.current_amount - paired.previous_amount, 2)::text AS change_amount,
        CASE WHEN paired.previous_amount <> 0
          THEN ROUND((paired.current_amount - paired.previous_amount) / ABS(paired.previous_amount) * 100, 2)::text
        END AS change_percent
      FROM paired
      LEFT JOIN category ON category.id = paired.category_id
      LEFT JOIN merchant ON merchant.id = paired.merchant_id
      WHERE paired.current_amount <> paired.previous_amount
        AND ${entityClause}
      ORDER BY ABS(paired.current_amount - paired.previous_amount) DESC, dimension_name
      LIMIT 20`,
    values
  };
}

export async function readInsightTrends(
  spec: InsightTrendsQuery,
  client?: PoolClient
): Promise<InsightTrendsResponse> {
  if (!client) return withAnalyticsSnapshot((snapshot) => readInsightTrends(spec, snapshot));
  const context = await readAnalyticsContext(client);
  const range = await resolveInsightRange(spec, client);
  const built = buildTrendsQuery(spec, range);
  const moversBuilt = buildMoversQuery(spec, range);
  const [result, moversResult, coverage] = await Promise.all([
    runQuery<TrendRow>(client, built.text, built.values),
    runQuery<MoverRow>(client, moversBuilt.text, moversBuilt.values),
    readInsightCoverage(spec, range, client)
  ]);
  const movers = moversResult.rows.map((row) => ({
    dimensionType: row.dimension_type,
    dimensionId: row.dimension_id,
    dimensionName: row.dimension_name,
    currentAmount: row.current_amount,
    previousAmount: row.previous_amount,
    changeAmount: row.change_amount,
    changePercent: row.change_percent
  }));
  return {
    baseCurrency: context.baseCurrency,
    range,
    groupBy: result.rows[0]?.dimension_type ?? effectiveDimension(spec),
    coverage,
    points: result.rows.map((row) => ({
      period: row.period,
      dimensionType: row.dimension_type,
      dimensionId: row.dimension_id,
      dimensionName: row.dimension_name,
      inflow: row.inflow,
      outflow: row.outflow,
      spending: row.spending,
      netCashflow: row.net_cashflow,
      trailingAverageSpending: row.trailing_average_spending,
      trailingMedianSpending: row.trailing_median_spending,
      monthOverMonth: row.previous_month_spending === null
        ? null
        : {
            current: row.spending,
            previous: row.previous_month_spending,
            change: row.month_change ?? '0',
            changePercent: row.month_change_percent
          },
      yearOverYear: row.previous_year_spending === null
        ? null
        : {
            current: row.spending,
            previous: row.previous_year_spending,
            change: row.year_change ?? '0',
            changePercent: row.year_change_percent
          },
      coverageStatus: row.coverage_status,
      missingValuationCount: Number(row.missing_valuation_count)
    })),
    movers: {
      positive: movers.filter((mover) => Number(mover.changeAmount) > 0).slice(0, 5),
      negative: movers.filter((mover) => Number(mover.changeAmount) < 0).slice(0, 5)
    }
  };
}

export function buildSeasonalityQuery(
  filters: EntityFilters,
  range: ResolvedRange,
  asOfDate = today()
): BuiltQuery {
  const values: unknown[] = [];
  const from = addValue(values, monthStart(range.from), '::date');
  const to = addValue(values, monthStart(range.to), '::date');
  const entityClause = aggregateEntityClause(filters, values, 'aggregate');
  const marketScope = addValue(values, filters.market ?? 'ALL');
  const liveAccountCompatibility = filters.accountId && filters.market
    ? `AND ${liveAccountMarketPredicate(addValue(values, filters.accountId), marketScope)}`
    : '';
  const asOf = addValue(values, asOfDate, '::date');
  return {
    text: `
      WITH eligible_period AS (
        SELECT ledger.period_start
        FROM analytics_monthly_current ledger
        WHERE ledger.dimension_type = 'ledger'
          AND ledger.market_scope = ${marketScope}
          AND ledger.coverage_status = 'complete'
          AND ledger.period_start < date_trunc('month', ${asOf})::date
          AND ledger.period_start BETWEEN ${from} AND ${to}
          ${liveAccountCompatibility}
      )
      SELECT
        EXTRACT(MONTH FROM eligible_period.period_start)::int AS month_number,
        COUNT(*)::int AS observation_count,
        ROUND(AVG(COALESCE(aggregate.spending_base, 0)), 2)::text AS average_spending,
        ROUND(
          PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY COALESCE(aggregate.spending_base, 0)
          )::numeric,
          2
        )::text AS median_spending
      FROM eligible_period
      LEFT JOIN analytics_monthly_current aggregate
        ON aggregate.period_start = eligible_period.period_start
       AND ${entityClause}
      GROUP BY EXTRACT(MONTH FROM eligible_period.period_start)
      ORDER BY month_number`,
    values
  };
}

export async function readInsightSeasonality(
  spec: InsightSeasonalityQuery,
  client?: PoolClient,
  options: InsightReadOptions = {}
): Promise<InsightSeasonalityResponse> {
  if (!client) {
    return withAnalyticsSnapshot((snapshot) => readInsightSeasonality(spec, snapshot, options));
  }
  const context = await readAnalyticsContext(client);
  const range = await resolveInsightRange(spec, client);
  const built = buildSeasonalityQuery(spec, range, options.asOfDate);
  // A PoolClient owns one PostgreSQL connection. Keep snapshot queries
  // sequential so cancellation and transaction ordering remain unambiguous.
  const result = await runQuery<SeasonalityRow>(client, built.text, built.values);
  const coverage = await readInsightCoverage(spec, range, client, options.sourceWatermark);
  const historyMonths = result.rows.reduce((total, row) => total + Number(row.observation_count), 0);
  const formatter = new Intl.DateTimeFormat('en', { month: 'short', timeZone: 'UTC' });
  return {
    baseCurrency: context.baseCurrency,
    range,
    status: historyMonths >= 12 ? 'available' : 'insufficient_history',
    historyMonths,
    requiredHistoryMonths: 12,
    coverage,
    months: historyMonths >= 12
      ? result.rows.map((row) => ({
          month: Number(row.month_number),
          monthName: formatter.format(new Date(Date.UTC(2024, Number(row.month_number) - 1, 1))),
          observationCount: Number(row.observation_count),
          averageSpending: row.average_spending,
          medianSpending: row.median_spending
        }))
      : []
  };
}

function recurringWhere(spec: InsightRecurringQuery, range: ResolvedRange, values: unknown[]) {
  const clauses = [recurringFilterClauses(spec, range, values)];
  if (spec.status) clauses.push(`series.status = ${addValue(values, spec.status)}`);
  if (spec.cadence) {
    clauses.push(`COALESCE(series.cadence_override, series.detected_cadence) = ${addValue(values, spec.cadence)}`);
  }
  return clauses.join(' AND ');
}

export function buildRecurringQueries(
  spec: InsightRecurringQuery,
  range: ResolvedRange,
  seriesId?: string,
  asOfDate = today()
) {
  const values: unknown[] = [];
  const clauses: string[] = [];
  if (seriesId) clauses.push(`series.id = ${addValue(values, seriesId)}::uuid`);
  clauses.push(recurringWhere(spec, range, values));
  const where = clauses.join(' AND ');
  const count: BuiltQuery = {
    text: `SELECT COUNT(*)::int AS total FROM recurring_series series WHERE ${where}`,
    values: [...values]
  };
  // A series qualifies through an occurrence in the selected range. Keep the
  // evidence projected for that series on the same range as well: otherwise a
  // narrow Ask/Insights filter can expose all-history occurrence counts and
  // price changes under a range-specific heading.
  const occurrenceFrom = addValue(values, range.from, '::date');
  const occurrenceTo = addValue(values, range.to, '::date');
  const asOf = addValue(values, asOfDate, '::date');
  const limit = addValue(values, spec.pageSize);
  const offset = addValue(values, (spec.page - 1) * spec.pageSize);
  const data: BuiltQuery = {
    text: `
      SELECT
        series.id::text,
        series.merchant_id::text,
        COALESCE(merchant.canonical_name, series.merchant_key) AS merchant_name,
        account_context.account_id,
        account_context.account_name,
        series.flow_type,
        COALESCE(series.cadence_override, series.detected_cadence) AS cadence,
        series.status,
        series.confidence::text,
        series.comparison_basis,
        COALESCE(series.expected_amount_override, series.detected_expected_amount)::text AS expected_amount,
        series.comparison_currency,
        occurrence_context.occurrence_count,
        occurrence_context.first_occurrence_date,
        occurrence_context.latest_occurrence_date,
        COALESCE(series.next_date_override, series.detected_next_date)::text AS expected_next_date,
        (
          series.status IN ('detected', 'confirmed')
          AND COALESCE(series.next_date_override, series.detected_next_date) < ${asOf}
        ) AS overdue,
        occurrence_context.latest_change_percent,
        (
          series.cadence_override IS NOT NULL
          OR series.expected_amount_override IS NOT NULL
          OR series.next_date_override IS NOT NULL
        ) AS user_corrected,
        occurrence_context.occurrences
      FROM recurring_series series
      LEFT JOIN merchant ON merchant.id = series.merchant_id
      LEFT JOIN LATERAL (
        SELECT
          CASE WHEN COUNT(DISTINCT ledger_txn.account_id) = 1
            THEN (ARRAY_AGG(DISTINCT ledger_txn.account_id))[1]::text END AS account_id,
          CASE WHEN COUNT(DISTINCT ledger_txn.account_id) = 1
            THEN (ARRAY_AGG(DISTINCT account.display_name))[1]
            WHEN COUNT(DISTINCT ledger_txn.account_id) > 1 THEN 'Multiple accounts'
          END AS account_name
        FROM recurring_occurrence occurrence
        JOIN txn ledger_txn ON ledger_txn.id = occurrence.transaction_id
        JOIN account ON account.id = ledger_txn.account_id
        WHERE occurrence.series_id = series.id
          AND occurrence.occurrence_date BETWEEN ${occurrenceFrom} AND ${occurrenceTo}
      ) account_context ON true
      LEFT JOIN LATERAL (
        WITH ranked AS (
          SELECT
            occurrence.*,
            ROW_NUMBER() OVER (ORDER BY occurrence.occurrence_date DESC, occurrence.occurrence_number DESC) AS recent_rank
          FROM recurring_occurrence occurrence
          WHERE occurrence.series_id = series.id
            AND occurrence.occurrence_date BETWEEN ${occurrenceFrom} AND ${occurrenceTo}
        )
        SELECT
          COUNT(*)::int AS occurrence_count,
          MIN(occurrence_date)::text AS first_occurrence_date,
          MAX(occurrence_date)::text AS latest_occurrence_date,
          CASE WHEN MAX(comparison_amount) FILTER (WHERE recent_rank = 2) <> 0
            THEN ROUND(
              (MAX(comparison_amount) FILTER (WHERE recent_rank = 1)
                - MAX(comparison_amount) FILTER (WHERE recent_rank = 2))
              / ABS(MAX(comparison_amount) FILTER (WHERE recent_rank = 2)) * 100,
              2
            )::text
          END AS latest_change_percent,
          COALESCE(jsonb_agg(jsonb_build_object(
            'id', transaction_id::text,
            'transactionId', transaction_id::text,
            'bookedDate', occurrence_date::text,
            'amount', comparison_amount::text,
            'currency', comparison_currency
          ) ORDER BY occurrence_number), '[]'::jsonb) AS occurrences
        FROM ranked
      ) occurrence_context ON true
      WHERE ${where}
      ORDER BY
        CASE series.status WHEN 'detected' THEN 0 WHEN 'confirmed' THEN 1 WHEN 'cancelled' THEN 2 ELSE 3 END,
        overdue DESC,
        expected_next_date,
        series.id
      LIMIT ${limit} OFFSET ${offset}`,
    values
  };
  return { data, count };
}

function mapRecurring(row: RecurringRow): RecurringSeries {
  const occurrences = parseJsonArray(row.occurrences).flatMap((value) => {
    if (!value || typeof value !== 'object') return [];
    const item = value as Record<string, unknown>;
    if (typeof item.transactionId !== 'string' || typeof item.bookedDate !== 'string') return [];
    return [{
      id: typeof item.id === 'string' ? item.id : item.transactionId,
      transactionId: item.transactionId,
      bookedDate: item.bookedDate,
      amount: typeof item.amount === 'string' ? item.amount : String(item.amount ?? '0'),
      currency: typeof item.currency === 'string' ? item.currency : row.comparison_currency
    }];
  });
  return {
    id: row.id,
    merchantId: row.merchant_id,
    merchantName: row.merchant_name,
    accountId: row.account_id,
    accountName: row.account_name,
    direction: row.flow_type,
    cadence: row.cadence,
    status: row.status,
    confidence: row.confidence,
    comparisonBasis: row.comparison_basis,
    expectedAmount: row.expected_amount,
    currency: row.comparison_currency,
    occurrenceCount: Number(row.occurrence_count),
    firstOccurrenceDate: row.first_occurrence_date,
    lastOccurrenceDate: row.latest_occurrence_date,
    expectedNextDate: row.expected_next_date,
    overdue: row.overdue,
    latestChangePercent: row.latest_change_percent,
    userCorrected: row.user_corrected,
    occurrences
  };
}

export async function readInsightRecurring(
  spec: InsightRecurringQuery,
  client?: PoolClient,
  options: InsightReadOptions = {}
): Promise<InsightRecurringResponse> {
  if (!client) {
    return withAnalyticsSnapshot((snapshot) => readInsightRecurring(spec, snapshot, options));
  }
  const context = await readAnalyticsContext(client);
  const range = await resolveInsightRange(spec, client);
  const built = buildRecurringQueries(spec, range, undefined, options.asOfDate);
  const data = await runQuery<RecurringRow>(client, built.data.text, built.data.values);
  const count = await runQuery<{ total: number }>(client, built.count.text, built.count.values);
  const total = Number(count.rows[0]?.total ?? 0);
  return {
    baseCurrency: context.baseCurrency,
    range,
    series: data.rows.map(mapRecurring),
    page: spec.page,
    pageSize: spec.pageSize,
    total,
    totalPages: total === 0 ? 0 : Math.ceil(total / spec.pageSize)
  };
}

async function readRecurringById(id: string) {
  const scopeResult = await query<{ market_scope: 'ALL' | MarketCode }>(
    `SELECT market_scope
     FROM recurring_series
     WHERE id = $1::uuid
       AND last_detected_generation = ${activePublishedGenerationSql}`,
    [id]
  );
  const scope = scopeResult.rows[0]?.market_scope;
  if (!scope) return null;
  const spec: InsightRecurringQuery = {
    range: 'all',
    page: 1,
    pageSize: 100,
    ...(scope === 'ALL' ? {} : { market: scope })
  };
  const range = await resolveInsightRange(spec);
  const built = buildRecurringQueries(spec, range, id);
  const result = await query<RecurringRow>(built.data.text, built.data.values);
  return result.rows[0] ? mapRecurring(result.rows[0]) : null;
}

export function buildRecurringReviewUpdate(id: string, patch: RecurringPatch): BuiltQuery {
  const values: unknown[] = [];
  const updates: string[] = [];
  if (patch.status !== undefined) {
    updates.push(`status = ${addValue(values, patch.status)}`);
  }
  if (patch.cadence !== undefined) {
    updates.push(`cadence_override = ${addValue(values, patch.cadence)}`);
  }
  if (patch.expectedAmount !== undefined) {
    updates.push(`expected_amount_override = ${addValue(values, patch.expectedAmount)}::numeric`);
  }
  updates.push('reviewed_at = now()', 'updated_at = now()');
  values.push(id);
  return {
    text: `UPDATE recurring_series
      SET ${updates.join(', ')}
      WHERE id = $${values.length}::uuid
        AND last_detected_generation = ${activePublishedGenerationSql}
      RETURNING id::text`,
    values
  };
}

export async function updateRecurringSeries(id: string, patch: RecurringPatch) {
  const built = buildRecurringReviewUpdate(id, patch);
  const result = await query<{ id: string }>(built.text, built.values);
  if (!result.rows[0]) return null;
  // Recurrence corrections are detector inputs. Refresh findings after the
  // durable override is saved so cancelled/ignored series and amount/cadence
  // changes resolve or rebuild their dependent evidence.
  await enqueueAnalyticsRefresh('incremental').catch(() => undefined);
  return readRecurringById(id);
}

function findingsWhere(spec: InsightFindingsQuery, range: ResolvedRange, values: unknown[]) {
  const clauses = [
    `${findingEventDate} BETWEEN ${addValue(values, range.from, '::date')} AND ${addValue(values, range.to, '::date')}`
  ];
  clauses.push(...findingEntityClauses(spec, values));
  if (spec.type) clauses.push(`finding.finding_type = ${addValue(values, spec.type)}`);
  if (spec.status) clauses.push(`finding.status = ${addValue(values, spec.status)}`);
  if (spec.severity) clauses.push(`finding.severity = ${addValue(values, spec.severity)}`);
  return clauses.join(' AND ');
}

const findingJoins = `
  LEFT JOIN txn ledger_txn ON ledger_txn.id = finding.transaction_id
  LEFT JOIN account ON account.id = COALESCE(finding.account_id, ledger_txn.account_id)
  LEFT JOIN category ON category.id = ${findingCategoryId}
  LEFT JOIN recurring_series series ON series.id = finding.recurring_series_id
  LEFT JOIN merchant transaction_merchant ON transaction_merchant.id = ledger_txn.merchant_id
  LEFT JOIN merchant series_merchant ON series_merchant.id = series.merchant_id
  LEFT JOIN merchant evidence_merchant ON evidence_merchant.id = ${findingMerchantId}`;

export function buildFindingQueries(spec: InsightFindingsQuery, range: ResolvedRange) {
  const values: unknown[] = [];
  const where = findingsWhere(spec, range, values);
  const count: BuiltQuery = {
    text: `SELECT COUNT(*)::int AS total FROM insight_finding finding ${findingJoins} WHERE ${where}`,
    values: [...values]
  };
  const limit = addValue(values, spec.pageSize);
  const offset = addValue(values, (spec.page - 1) * spec.pageSize);
  const data: BuiltQuery = {
    text: `
      SELECT
        finding.id::text,
        finding.finding_type,
        finding.status,
        finding.severity,
        finding.headline,
        COALESCE(
          NULLIF(finding.evidence ->> 'summary', ''),
          NULLIF(finding.evidence ->> 'explanation', ''),
          'Open the stored evidence to inspect this deterministic finding.'
        ) AS summary,
        COALESCE(finding.account_id, ledger_txn.account_id)::text AS account_id,
        account.display_name AS account_name,
        ${findingCategoryId}::text AS category_id,
        category.name AS category_name,
        ${findingMerchantId}::text AS merchant_id,
        COALESCE(
          transaction_merchant.canonical_name,
          series_merchant.canonical_name,
          evidence_merchant.canonical_name,
          series.merchant_key
        ) AS merchant_name,
        finding.recurring_series_id::text,
        finding.detector_fingerprint,
        finding.evidence,
        finding.first_seen_at,
        finding.last_seen_at,
        finding.reviewed_at
      FROM insight_finding finding
      ${findingJoins}
      WHERE ${where}
      ORDER BY
        CASE finding.status WHEN 'new' THEN 0 WHEN 'confirmed' THEN 1 WHEN 'dismissed' THEN 2 ELSE 3 END,
        CASE finding.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
        finding.last_seen_at DESC,
        finding.id
      LIMIT ${limit} OFFSET ${offset}`,
    values
  };
  return { data, count };
}

function evidenceObject(value: unknown): Record<string, unknown> {
  const withoutMigrationMetadata = (evidence: Record<string, unknown>) => {
    const publicEvidence = { ...evidence };
    delete publicEvidence._migration014DetectorFingerprint;
    return publicEvidence;
  };
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return withoutMigrationMetadata(value as Record<string, unknown>);
  }
  if (typeof value === 'string') {
    try {
      const parsed: unknown = JSON.parse(value);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? withoutMigrationMetadata(parsed as Record<string, unknown>)
        : {};
    } catch {
      return {};
    }
  }
  return {};
}

function mapFinding(row: FindingRow): InsightFinding {
  return {
    id: row.id,
    type: row.finding_type,
    status: row.status,
    severity: row.severity,
    title: row.headline,
    summary: row.summary,
    accountId: row.account_id,
    accountName: row.account_name,
    categoryId: row.category_id,
    categoryName: row.category_name,
    merchantId: row.merchant_id,
    merchantName: row.merchant_name,
    recurringSeriesId: row.recurring_series_id,
    detectorFingerprint: row.detector_fingerprint,
    evidence: evidenceObject(row.evidence),
    firstSeenAt: timestamp(row.first_seen_at)!,
    lastSeenAt: timestamp(row.last_seen_at)!,
    reviewedAt: timestamp(row.reviewed_at)
  };
}

export async function readInsightFindings(
  spec: InsightFindingsQuery,
  client?: PoolClient
): Promise<InsightFindingsResponse> {
  if (!client) return withAnalyticsSnapshot((snapshot) => readInsightFindings(spec, snapshot));
  const context = await readAnalyticsContext(client);
  const range = await resolveInsightRange(spec, client);
  const built = buildFindingQueries(spec, range);
  const data = await runQuery<FindingRow>(client, built.data.text, built.data.values);
  const count = await runQuery<{ total: number }>(client, built.count.text, built.count.values);
  const total = Number(count.rows[0]?.total ?? 0);
  return {
    baseCurrency: context.baseCurrency,
    findings: data.rows.map(mapFinding),
    page: spec.page,
    pageSize: spec.pageSize,
    total,
    totalPages: total === 0 ? 0 : Math.ceil(total / spec.pageSize)
  };
}

async function readFindingById(id: string) {
  const result = await query<FindingRow>(
    `SELECT
       finding.id::text,
       finding.finding_type,
       finding.status,
       finding.severity,
       finding.headline,
       COALESCE(
         NULLIF(finding.evidence ->> 'summary', ''),
         NULLIF(finding.evidence ->> 'explanation', ''),
         'Open the stored evidence to inspect this deterministic finding.'
       ) AS summary,
       COALESCE(finding.account_id, ledger_txn.account_id)::text AS account_id,
       account.display_name AS account_name,
       ${findingCategoryId}::text AS category_id,
       category.name AS category_name,
       ${findingMerchantId}::text AS merchant_id,
       COALESCE(
         transaction_merchant.canonical_name,
         series_merchant.canonical_name,
         evidence_merchant.canonical_name,
         series.merchant_key
       ) AS merchant_name,
       finding.recurring_series_id::text,
       finding.detector_fingerprint,
       finding.evidence,
       finding.first_seen_at,
       finding.last_seen_at,
       finding.reviewed_at
     FROM insight_finding finding
     ${findingJoins}
     WHERE finding.id = $1::uuid
       AND finding.last_detected_generation = ${activePublishedGenerationSql}`,
    [id]
  );
  return result.rows[0] ? mapFinding(result.rows[0]) : null;
}

export function buildFindingReviewUpdate(id: string, patch: InsightFindingPatch): BuiltQuery {
  return {
    text: `UPDATE insight_finding
      SET status = $1,
          reviewed_at = CASE WHEN $1 IN ('confirmed', 'dismissed') THEN now() ELSE reviewed_at END,
          resolved_at = CASE WHEN $1 = 'resolved' THEN now() ELSE NULL END,
          updated_at = now()
      WHERE id = $2::uuid
        AND last_detected_generation = ${activePublishedGenerationSql}
      RETURNING id::text`,
    values: [patch.status, id]
  };
}

export async function updateInsightFinding(id: string, patch: InsightFindingPatch) {
  const built = buildFindingReviewUpdate(id, patch);
  const result = await query<{ id: string }>(built.text, built.values);
  if (!result.rows[0]) return null;
  return readFindingById(id);
}

export async function readInsightSettings(): Promise<InsightSettingsResponse> {
  const result = await query<{ sensitivity: InsightSettingsResponse['settings']['sensitivity']; updated_at: Date | string }>(
    `SELECT sensitivity, updated_at FROM analytics_settings WHERE singleton`
  );
  const row = result.rows[0];
  if (!row) throw new Error('Analytics settings row is missing');
  return { settings: { sensitivity: row.sensitivity, updatedAt: timestamp(row.updated_at)! } };
}

export async function enqueueAnalyticsRefreshInTransaction(
  client: PoolClient,
  mode: 'full' | 'incremental'
) {
  // Serialize API callers on the singleton settings row. Worker and trigger
  // producers do not share that mutex, so the partial unique index below still
  // arbitrates cross-producer races.
  await client.query(
    'SELECT singleton FROM analytics_settings WHERE singleton FOR UPDATE'
  );

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const inserted = await client.query<{ id: string; status: 'queued' }>(
      `INSERT INTO job (kind, payload, status, deduplication_key)
       VALUES ('analytics_refresh', $1::jsonb, 'queued', 'analytics-refresh:ledger')
       ON CONFLICT (kind, deduplication_key)
         WHERE deduplication_key IS NOT NULL
           AND status IN ('queued', 'claimed')
       DO NOTHING
       RETURNING id::text, status`,
      [JSON.stringify({ mode })]
    );
    const accepted = inserted.rows[0];
    if (accepted) {
      const run = await client.query<{ id: string }>(
        `INSERT INTO analytics_run (
           mode, status, base_currency, threshold_policy_version
         )
         SELECT $1, 'queued', ledger.base_currency, profile.policy_version
         FROM ledger_settings ledger
         JOIN analytics_threshold_profile profile
           ON profile.base_currency = ledger.base_currency
         WHERE ledger.singleton
         RETURNING id::text`,
        [mode]
      );
      const analyticsRun = run.rows[0];
      if (!analyticsRun) throw new Error('Analytics run insert did not return a row');
      const attached = await client.query<{ id: string }>(
        `UPDATE job
         SET payload = payload || jsonb_build_object('analytics_run_id', $2::text),
             updated_at = now()
         WHERE id = $1::uuid AND status = 'queued'
         RETURNING id::text`,
        [accepted.id, analyticsRun.id]
      );
      if (!attached.rows[0]) throw new Error('Analytics run could not be attached to its job');
      return { jobId: accepted.id, kind: 'analytics_refresh' as const, status: accepted.status };
    }

    const active = await client.query<{ id: string; status: 'queued' | 'claimed' }>(
      `UPDATE job
       SET payload = payload
         || CASE WHEN $1 = 'full' THEN '{"mode":"full"}'::jsonb ELSE '{}'::jsonb END
         || '{"rerun_requested":true}'::jsonb,
           updated_at = now()
       WHERE kind = 'analytics_refresh'
         AND status IN ('queued', 'claimed')
       RETURNING id::text, status`,
      [mode]
    );
    if (active.rows[0]) {
      return {
        jobId: active.rows[0].id,
        kind: 'analytics_refresh' as const,
        status: active.rows[0].status
      };
    }
    // The conflicting job completed between our INSERT and UPDATE. Retry so
    // this request still guarantees that one active refresh exists.
  }

  throw new Error('Analytics refresh could not be enqueued or coalesced');
}

export async function updateInsightSettings(patch: InsightSettingsPatch): Promise<InsightSettingsResponse> {
  const client = await getPool().connect();
  let committed = false;
  try {
    await client.query('BEGIN');
    const result = await client.query<{
      sensitivity: InsightSettingsResponse['settings']['sensitivity'];
      updated_at: Date | string;
    }>(
      `UPDATE analytics_settings
       SET sensitivity = $1, updated_at = now()
       WHERE singleton
       RETURNING sensitivity, updated_at`,
      [patch.sensitivity]
    );
    const row = result.rows[0];
    if (!row) throw new Error('Analytics settings row is missing');
    const refresh = await enqueueAnalyticsRefreshInTransaction(client, 'full');
    await client.query('COMMIT');
    committed = true;
    return {
      settings: { sensitivity: row.sensitivity, updatedAt: timestamp(row.updated_at)! },
      refresh
    };
  } catch (error) {
    if (!committed) await client.query('ROLLBACK').catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

export async function enqueueAnalyticsRefresh(mode: 'full' | 'incremental') {
  const client = await getPool().connect();
  let committed = false;
  try {
    await client.query('BEGIN');
    const accepted = await enqueueAnalyticsRefreshInTransaction(client, mode);
    await client.query('COMMIT');
    committed = true;
    return accepted;
  } catch (error) {
    if (!committed) await client.query('ROLLBACK').catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}
