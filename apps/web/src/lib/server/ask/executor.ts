import { createHash } from 'node:crypto';

import type {
  AskClarificationChoice,
  AskCoverage,
  AskEvidence,
  AskExecutePlanV1,
  AskLocalClarificationReference,
  AskMarket,
  AskQueryV1,
  AskResolvedQuery,
  AskResponseContext,
  InsightFindingsQuery,
  InsightRecurringQuery,
  InsightSeasonalityQuery
} from '@ledger/shared-types';
import type { PoolClient, QueryResultRow } from 'pg';

import { buildFxAnalyticsQuery, transactionFlowSql } from '../db.js';
import {
  readInsightCoverage,
  readInsightFindings,
  readInsightRecurring,
  readInsightSeasonality
} from '../insights.js';
import { comparisonRange, resolveAskRange, type ResolvedAskRange } from './time.js';

export class AskAnalyticsRebuildingError extends Error {
  constructor() {
    super('Insights are rebuilding for the active home currency.');
    this.name = 'AskAnalyticsRebuildingError';
  }
}

export class AskInvalidEntitySelectionError extends Error {
  constructor() {
    super('The selected local entity is no longer valid for this query and scope.');
    this.name = 'AskInvalidEntitySelectionError';
  }
}

export type AskFact = {
  id: string;
  role: 'summary' | 'comparison' | 'trend' | 'evidence' | 'coverage';
  dataset: AskQueryV1['dataset'];
  text: string;
};

type AnalyticsContextRow = {
  base_currency: string;
  generation: string | number | null;
  threshold_policy_version: string | null;
  source_watermark: Date | string | null;
  fx_rate_watermark: Date | string | null;
  source_changed: boolean;
  fx_rates_changed: boolean;
};

export type AskAnalyticsContext = Omit<AskResponseContext, 'resolvedQueries'> & {
  /** Internal generation cutoff; never crosses the public response boundary. */
  fxRateCutoff?: string | null;
  /** True when live FX reference data is newer than the published generation. */
  fxRatesChangedSinceGeneration?: boolean;
};

export type AskExecutionResult = {
  evidence: AskEvidence[];
  facts: AskFact[];
  context: AskResponseContext;
  warnings: string[];
};

export type AskEntityClarification = {
  prompt: string;
  choices: AskClarificationChoice[];
  plan: AskExecutePlanV1;
};

type ResolvedEntity = {
  kind: 'account' | 'category' | 'merchant';
  id: string;
  label: string;
};

type EntityRow = QueryResultRow & {
  id: string;
  label: string;
  market_code: 'CA' | 'TZ' | null;
  qualifier: string | null;
};

type IndexedEntityRow = {
  row: EntityRow;
  choice: string;
};

const completeCoverage = (): AskCoverage => ({
  status: 'complete',
  valuedTransactionCount: 0,
  pendingFxCount: 0,
  pendingByCurrency: []
});

function boundedFactText(value: string) {
  return value.length <= 500 ? value : `${value.slice(0, 499)}…`;
}

function factExcerpt(value: string, limit: number) {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}

function boundedEvidence(value: AskEvidence): AskEvidence {
  let truncated = value.truncated;
  const rows = value.rows.map((row) => Object.fromEntries(
    Object.entries(row).map(([key, cell]) => {
      if (typeof cell === 'string' && cell.length > 500) truncated = true;
      return [key, typeof cell === 'string' ? factExcerpt(cell, 500) : cell];
    })
  ));
  return {
    ...value,
    rows,
    truncated
  };
}

function asTimestamp(value: Date | string | null) {
  if (value === null) return null;
  // PostgreSQL timestamps can carry six fractional digits. Preserve textual
  // values exactly so a generation watermark never rounds backward through
  // JavaScript's millisecond-only Date representation.
  return value instanceof Date ? value.toISOString() : value;
}

export async function readAskAnalyticsContext(
  client: PoolClient,
  market: AskMarket,
  asOfDate: string,
  timeZone: string
): Promise<AskAnalyticsContext> {
  const result = await client.query<AnalyticsContextRow>(
    `WITH fx_context AS (
       SELECT MAX(fetched_at) AS latest_rate_at FROM fx_rate
     )
     SELECT
       ledger.base_currency,
       run.generation,
       run.threshold_policy_version,
       CASE WHEN run.source_watermark IS NULL THEN NULL ELSE
         to_char(
           run.source_watermark AT TIME ZONE 'UTC',
           'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
         )
       END AS source_watermark,
       run.result ->> 'fx_rate_watermark' AS fx_rate_watermark,
       (
         GREATEST(
           COALESCE((SELECT MAX(updated_at) FROM txn), '-infinity'::timestamptz),
           COALESCE((SELECT MAX(updated_at) FROM statement), '-infinity'::timestamptz),
           COALESCE((SELECT MAX(updated_at) FROM account), '-infinity'::timestamptz),
           COALESCE((SELECT MAX(updated_at) FROM category), '-infinity'::timestamptz),
           COALESCE((SELECT MAX(updated_at) FROM merchant), '-infinity'::timestamptz)
         ) > COALESCE(run.source_watermark, '-infinity'::timestamptz)
       ) AS source_changed,
       (
         fx_context.latest_rate_at IS NOT NULL
         AND (
           run.result ->> 'fx_rate_watermark' IS NULL
           OR fx_context.latest_rate_at > (run.result ->> 'fx_rate_watermark')::timestamptz
         )
       ) AS fx_rates_changed
     FROM ledger_settings ledger
     CROSS JOIN fx_context
     LEFT JOIN analytics_settings settings ON settings.singleton
     LEFT JOIN analytics_run run
       ON run.generation = settings.published_generation
      AND run.base_currency = ledger.base_currency
      AND run.status = 'succeeded'
     WHERE ledger.singleton`
  );
  const row = result.rows[0];
  if (!row?.generation || !row.threshold_policy_version) throw new AskAnalyticsRebuildingError();
  return {
    market,
    baseCurrency: row.base_currency,
    asOfDate,
    timeZone,
    analyticsGeneration: Number(row.generation),
    thresholdPolicyVersion: row.threshold_policy_version,
    sourceWatermark: asTimestamp(row.source_watermark),
    sourceChangedSinceGeneration: row.source_changed,
    coverage: completeCoverage(),
    fxRateCutoff: asTimestamp(row.fx_rate_watermark),
    fxRatesChangedSinceGeneration: row.fx_rates_changed
  };
}

function normalizeEntity(value: string) {
  return value.normalize('NFKC').trim().replace(/\s+/g, ' ').toLocaleLowerCase('en');
}

async function entityRows(client: PoolClient, kind: ResolvedEntity['kind']) {
  if (kind === 'account') {
    return client.query<EntityRow>(
      `SELECT id::text, display_name AS label, market_code, account_ref_masked AS qualifier
       FROM account ORDER BY display_name, market_code, account_ref_masked NULLS LAST, id`
    );
  }
  if (kind === 'category') {
    return client.query<EntityRow>(
      `SELECT category.id::text, category.name AS label, NULL::text AS market_code,
         COALESCE(parent.name, initcap(category.kind)) AS qualifier
       FROM category
       LEFT JOIN category parent ON parent.id = category.parent_id
       WHERE category.archived_at IS NULL
       ORDER BY category.name, parent.name NULLS FIRST, category.id`
    );
  }
  return client.query<EntityRow>(
    `SELECT id::text, canonical_name AS label, NULL::text AS market_code, NULL::text AS qualifier
     FROM merchant ORDER BY canonical_name, id`
  );
}

function localEntityChoice(rows: EntityRow[], row: EntityRow, index: number) {
  const sameLabelCount = rows.filter((candidate) => normalizeEntity(candidate.label) === normalizeEntity(row.label)).length;
  const market = row.market_code === 'CA' ? 'Canada' : row.market_code === 'TZ' ? 'Tanzania' : null;
  const qualifier = row.qualifier || (sameLabelCount > 1 ? `option ${index + 1}` : null);
  return [row.label, market, qualifier].filter(Boolean).join(' · ').slice(0, 120);
}

function opaqueEntityToken(kind: ResolvedEntity['kind'], id: string) {
  return createHash('sha256').update(`ledger-ask-entity-v1\0${kind}\0${id}`).digest('hex');
}

function exactEntityMatches(indexed: IndexedEntityRow[], wanted: string) {
  const decorated = indexed.filter(({ choice }) => normalizeEntity(choice) === wanted);
  return decorated.length > 0
    ? decorated
    : indexed.filter(({ row }) => normalizeEntity(row.label) === wanted);
}

function suggestedEntityMatches(indexed: IndexedEntityRow[], wanted: string) {
  return indexed.filter(({ row, choice }) =>
    normalizeEntity(row.label).includes(wanted)
    || wanted.includes(normalizeEntity(row.label))
    || normalizeEntity(choice).includes(wanted)
  );
}

function selectableEntityMatches(indexed: IndexedEntityRow[], wanted: string) {
  const exact = exactEntityMatches(indexed, wanted);
  return (exact.length > 0 ? exact : suggestedEntityMatches(indexed, wanted)).slice(0, 5);
}

function localClarificationChoices(
  query: AskQueryV1,
  candidates: IndexedEntityRow[]
): AskClarificationChoice[] {
  if (!query.entity) return [];
  return candidates.slice(0, 5).map(({ row, choice }) => ({
    label: choice,
    localSelection: {
      queryId: query.id,
      entityToken: opaqueEntityToken(query.entity!.kind, row.id)
    }
  }));
}

function widenSelectedAccountQuery(plan: AskExecutePlanV1, queryId: AskQueryV1['id']): AskExecutePlanV1 {
  return {
    ...plan,
    queries: plan.queries.map((candidate) => candidate.id === queryId
      ? { ...candidate, market: 'ALL' as const }
      : candidate)
  };
}

async function resolveSelectedEntity(
  client: PoolClient,
  query: AskQueryV1,
  market: AskMarket,
  selection: AskLocalClarificationReference
): Promise<ResolvedEntity> {
  if (!query.entity || selection.queryId !== query.id) throw new AskInvalidEntitySelectionError();
  const result = await entityRows(client, query.entity.kind);
  const indexed = result.rows.map((row, index) => ({
    row,
    choice: localEntityChoice(result.rows, row, index)
  }));
  const scoped = query.entity.kind === 'account' && market !== 'ALL'
    ? indexed.filter(({ row }) => row.market_code === market)
    : indexed;
  const candidates = selectableEntityMatches(scoped, normalizeEntity(query.entity.term));
  const selected = candidates.filter(({ row }) =>
    opaqueEntityToken(query.entity!.kind, row.id) === selection.entityToken
  );
  if (selected.length !== 1) throw new AskInvalidEntitySelectionError();
  const row = selected[0]!.row;
  return { kind: query.entity.kind, id: row.id, label: row.label };
}

async function resolveEntity(
  client: PoolClient,
  query: AskQueryV1,
  market: AskMarket,
  plan: AskExecutePlanV1
): Promise<ResolvedEntity | AskEntityClarification | undefined> {
  if (!query.entity) return undefined;
  const result = await entityRows(client, query.entity.kind);
  const wanted = normalizeEntity(query.entity.term);
  const indexed = result.rows.map((row, index) => ({ row, choice: localEntityChoice(result.rows, row, index) }));
  const scoped = query.entity.kind === 'account' && market !== 'ALL'
    ? indexed.filter(({ row }) => row.market_code === market)
    : indexed;
  const exact = exactEntityMatches(scoped, wanted);
  if (exact.length === 1) {
    const row = exact[0]!.row;
    return { kind: query.entity.kind, id: row.id, label: row.label };
  }
  if (query.entity.kind === 'account' && market !== 'ALL' && exact.length === 0) {
    const outside = indexed.filter(({ row, choice }) =>
      row.market_code !== market
      && (normalizeEntity(row.label) === wanted || normalizeEntity(choice) === wanted)
    );
    if (outside.length > 0) {
      const widenedPlan = widenSelectedAccountQuery(plan, query.id);
      return {
        prompt: `${query.entity.term} is not in the requested ${market === 'CA' ? 'Canada' : 'Tanzania'} scope. Which matching account should I use?`,
        choices: localClarificationChoices(query, outside),
        plan: widenedPlan
      };
    }
  }
  const suggestions = suggestedEntityMatches(scoped, wanted).slice(0, 5);
  return {
    prompt: exact.length > 1
      ? `More than one ${query.entity.kind} is named “${query.entity.term}”. Which one did you mean?`
      : `I could not match the ${query.entity.kind} “${query.entity.term}”. Which one did you mean?`,
    choices: localClarificationChoices(query, exact.length > 1 ? exact : suggestions),
    plan
  };
}

function marketCode(market: AskMarket) {
  return market === 'ALL' ? undefined : market;
}

async function earliestDate(
  client: PoolClient,
  market: AskMarket,
  entity: ResolvedEntity | undefined,
  fallback: string,
  watermark: string | null
) {
  const values: unknown[] = [];
  const conditions: string[] = [];
  const add = (value: unknown) => { values.push(value); return `$${values.length}`; };
  const scoped = marketCode(market);
  if (scoped) conditions.push(`a.market_code = ${add(scoped)}`);
  if (entity?.kind === 'account') conditions.push(`t.account_id = ${add(entity.id)}::uuid`);
  if (entity?.kind === 'category') conditions.push(`t.category_id = ${add(entity.id)}::uuid`);
  if (entity?.kind === 'merchant') conditions.push(`t.merchant_id = ${add(entity.id)}::uuid`);
  if (watermark) conditions.push(`t.updated_at <= ${add(watermark)}::timestamptz`);
  const result = await client.query<{ earliest: string }>(
    `SELECT COALESCE(MIN(t.booked_date), ${add(fallback)}::date)::text AS earliest
     FROM txn t JOIN account a ON a.id = t.account_id
     ${conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''}`,
    values
  );
  return result.rows[0]?.earliest ?? fallback;
}

async function rangeFor(
  client: PoolClient,
  query: AskQueryV1,
  market: AskMarket,
  entity: ResolvedEntity | undefined,
  context: AskAnalyticsContext
) {
  const earliest = query.date.kind === 'preset' && query.date.value === 'all'
    ? await earliestDate(client, market, entity, context.asOfDate, context.sourceWatermark)
    : context.asOfDate;
  return resolveAskRange(query.date, context.asOfDate, earliest);
}

function coverageFromAggregateRows(rows: Array<{
  total_valued_count?: unknown;
  total_pending_fx_count?: unknown;
  total_pending_by_currency?: unknown;
}>): AskCoverage {
  const first = rows[0];
  const valued = Number(first?.total_valued_count ?? 0);
  const pending = Number(first?.total_pending_fx_count ?? 0);
  const currencies = new Map<string, number>();
  const raw = first?.total_pending_by_currency;
  const object = typeof raw === 'string'
    ? (() => { try { return JSON.parse(raw) as unknown; } catch { return {}; } })()
    : raw;
  if (object && typeof object === 'object' && !Array.isArray(object)) {
    for (const [currency, count] of Object.entries(object as Record<string, unknown>)) {
      currencies.set(currency, Number(count ?? 0));
    }
  }
  return {
    status: pending > 0 ? 'partial' : 'complete',
    valuedTransactionCount: valued,
    pendingFxCount: pending,
    pendingByCurrency: [...currencies.entries()].sort().map(([currency, transactionCount]) => ({ currency, transactionCount }))
  };
}

function aggregateGroup(
  query: Extract<AskQueryV1, { dataset: 'aggregate' }>,
  entity: ResolvedEntity | undefined,
  dateExpression = 't.booked_date'
) {
  const group = query.groupBy;
  if (group === 'month') {
    return {
      id: `date_trunc('month', ${dateExpression})::date::text`,
      label: `to_char(date_trunc('month', ${dateExpression}), 'YYYY-MM')`
    };
  }
  if (group === 'account') return { id: 'a.id::text', label: 'a.display_name' };
  if (group === 'category') return { id: `COALESCE(c.id::text, 'uncategorized')`, label: `COALESCE(c.name, 'Uncategorized')` };
  if (group === 'merchant') return { id: `COALESCE(m.id::text, 'unknown')`, label: `COALESCE(m.canonical_name, 'Unknown merchant')` };
  return { id: `'total'::text`, label: entity ? `'Filtered activity'::text` : `'All activity'::text` };
}

type AggregateRow = QueryResultRow & {
  dimension_id: string;
  dimension_label: string;
  inflow: string;
  outflow: string;
  spending: string;
  net_cashflow: string;
  transaction_count: number;
  valued_count: number;
  pending_fx_count: number;
  total_valued_count: string | number;
  total_pending_fx_count: string | number;
  total_pending_by_currency: unknown;
  previous_inflow: string | null;
  previous_outflow: string | null;
  previous_spending: string | null;
  previous_net_cashflow: string | null;
  previous_transaction_count: number | null;
  previous_valued_count: number | null;
  previous_pending_fx_count: number | null;
  inflow_change: string | null;
  outflow_change: string | null;
  spending_change: string | null;
  net_cashflow_change: string | null;
  transaction_count_change: number | null;
  valued_count_change: number | null;
  pending_fx_count_change: number | null;
  inflow_change_percent: string | null;
  outflow_change_percent: string | null;
  spending_change_percent: string | null;
  net_cashflow_change_percent: string | null;
  transaction_count_change_percent: string | null;
  valued_count_change_percent: string | null;
  pending_fx_count_change_percent: string | null;
};

async function executeAggregate(
  client: PoolClient,
  query: Extract<AskQueryV1, { dataset: 'aggregate' }>,
  market: AskMarket,
  entity: ResolvedEntity | undefined,
  range: ResolvedAskRange,
  context: AskAnalyticsContext
) {
  const values: unknown[] = [];
  const add = (value: unknown, cast = '') => { values.push(value); return `$${values.length}${cast}`; };
  const filters: string[] = [];
  const scoped = marketCode(market);
  if (scoped) filters.push(`a.market_code = ${add(scoped)}`);
  if (entity?.kind === 'account') filters.push(`t.account_id = ${add(entity.id)}::uuid`);
  if (entity?.kind === 'category') filters.push(`t.category_id = ${add(entity.id)}::uuid`);
  if (entity?.kind === 'merchant') filters.push(`t.merchant_id = ${add(entity.id)}::uuid`);
  if (context.sourceWatermark) filters.push(`t.updated_at <= ${add(context.sourceWatermark)}::timestamptz`);
  const currentFrom = add(range.from, '::date');
  const currentTo = add(range.to, '::date');
  const prior = comparisonRange(range, query.comparison);
  const previousFrom = prior ? add(prior.from, '::date') : 'NULL::date';
  const previousTo = prior ? add(prior.to, '::date') : 'NULL::date';
  const flow = transactionFlowSql('t', 'a');
  const where = filters.length ? `AND ${filters.join(' AND ')}` : '';
  const currentGroup = aggregateGroup(query, entity);
  const mappedPreviousDate = query.comparison === 'previous_year'
    ? `(t.booked_date + INTERVAL '1 year')::date`
    : `(${currentFrom} + (t.booked_date - ${previousFrom}))`;
  const previousGroup = aggregateGroup(query, entity, mappedPreviousDate);
  const selectedBranch = (
    bucket: 'current' | 'previous',
    from: string,
    to: string,
    group: ReturnType<typeof aggregateGroup>
  ) => `
       SELECT '${bucket}'::text AS bucket,
         ${group.id} AS dimension_id,
         ${group.label} AS dimension_label,
         t.amount_base,
         t.currency_native,
         ${flow} AS flow_type
       FROM txn t
       JOIN account a ON a.id = t.account_id
       LEFT JOIN category c ON c.id = t.category_id
       LEFT JOIN merchant m ON m.id = t.merchant_id
       WHERE t.booked_date BETWEEN ${from} AND ${to} ${where}`;
  const selectedSql = prior
    ? `${selectedBranch('current', currentFrom, currentTo, currentGroup)}
       UNION ALL
       ${selectedBranch('previous', previousFrom, previousTo, previousGroup)}`
    : selectedBranch('current', currentFrom, currentTo, currentGroup);
  const groupClause = 'GROUP BY bucket, dimension_id, dimension_label';
  const limit = query.groupBy === 'month' ? 120 : query.limit;
  const orderMetric = query.comparison === 'none'
    ? query.metrics[0]
    : `${query.metrics[0]} - previous_${query.metrics[0]}`;
  const result = await client.query<AggregateRow>(
    `WITH selected AS (
       ${selectedSql}
     ), grouped AS (
       SELECT bucket, dimension_id, dimension_label,
         COALESCE(SUM(ABS(amount_base)) FILTER (WHERE amount_base IS NOT NULL AND flow_type = 'income'), 0) AS inflow,
         COALESCE(SUM(ABS(amount_base)) FILTER (WHERE amount_base IS NOT NULL AND flow_type IN ('spend', 'fee')), 0)
           - COALESCE(SUM(ABS(amount_base)) FILTER (WHERE amount_base IS NOT NULL AND flow_type = 'refund'), 0) AS outflow,
         COALESCE(SUM(ABS(amount_base)) FILTER (WHERE amount_base IS NOT NULL AND flow_type IN ('spend', 'fee')), 0)
           - COALESCE(SUM(ABS(amount_base)) FILTER (WHERE amount_base IS NOT NULL AND flow_type = 'refund'), 0) AS spending,
         COUNT(*)::int AS transaction_count,
         COUNT(*) FILTER (WHERE amount_base IS NOT NULL)::int AS valued_count,
         COUNT(*) FILTER (WHERE amount_base IS NULL)::int AS pending_fx_count
       FROM selected
       ${groupClause}
     ), current_coverage AS (
       SELECT
         COUNT(*) FILTER (WHERE amount_base IS NOT NULL)::int AS total_valued_count,
         COUNT(*) FILTER (WHERE amount_base IS NULL)::int AS total_pending_fx_count
       FROM selected
       WHERE bucket = 'current'
     ), pending_currency AS (
       SELECT COALESCE(jsonb_object_agg(currency_native, transaction_count), '{}'::jsonb)
         AS total_pending_by_currency
       FROM (
         SELECT currency_native, COUNT(*)::int AS transaction_count
         FROM selected
         WHERE bucket = 'current' AND amount_base IS NULL
         GROUP BY currency_native
       ) pending
     ), comparison_keys AS (
       SELECT dimension_id, MAX(dimension_label) AS dimension_label
       FROM grouped
       GROUP BY dimension_id
     ), paired AS (
       SELECT comparison_keys.dimension_id, comparison_keys.dimension_label,
         COALESCE(current.inflow, 0) AS inflow,
         COALESCE(current.outflow, 0) AS outflow,
         COALESCE(current.spending, 0) AS spending,
         COALESCE(current.inflow, 0) - COALESCE(current.outflow, 0) AS net_cashflow,
         COALESCE(current.transaction_count, 0)::int AS transaction_count,
         COALESCE(current.valued_count, 0)::int AS valued_count,
         COALESCE(current.pending_fx_count, 0)::int AS pending_fx_count,
         COALESCE(previous.inflow, 0) AS previous_inflow,
         COALESCE(previous.outflow, 0) AS previous_outflow,
         COALESCE(previous.spending, 0) AS previous_spending,
         COALESCE(previous.inflow, 0) - COALESCE(previous.outflow, 0) AS previous_net_cashflow,
         COALESCE(previous.transaction_count, 0)::int AS previous_transaction_count,
         COALESCE(previous.valued_count, 0)::int AS previous_valued_count,
         COALESCE(previous.pending_fx_count, 0)::int AS previous_pending_fx_count
       FROM comparison_keys
       LEFT JOIN grouped current
         ON current.bucket = 'current' AND current.dimension_id = comparison_keys.dimension_id
       LEFT JOIN grouped previous
         ON previous.bucket = 'previous' AND previous.dimension_id = comparison_keys.dimension_id
     )
     SELECT dimension_id, dimension_label,
       ROUND(inflow, 2)::text AS inflow, ROUND(outflow, 2)::text AS outflow,
       ROUND(spending, 2)::text AS spending, ROUND(net_cashflow, 2)::text AS net_cashflow,
       transaction_count, valued_count, pending_fx_count,
       current_coverage.total_valued_count,
       current_coverage.total_pending_fx_count,
       pending_currency.total_pending_by_currency,
       ROUND(previous_inflow, 2)::text AS previous_inflow,
       ROUND(previous_outflow, 2)::text AS previous_outflow,
       ROUND(previous_spending, 2)::text AS previous_spending,
       ROUND(previous_net_cashflow, 2)::text AS previous_net_cashflow,
       previous_transaction_count, previous_valued_count, previous_pending_fx_count,
       ROUND(inflow - previous_inflow, 2)::text AS inflow_change,
       ROUND(outflow - previous_outflow, 2)::text AS outflow_change,
       ROUND(spending - previous_spending, 2)::text AS spending_change,
       ROUND(net_cashflow - previous_net_cashflow, 2)::text AS net_cashflow_change,
       transaction_count - previous_transaction_count AS transaction_count_change,
       valued_count - previous_valued_count AS valued_count_change,
       pending_fx_count - previous_pending_fx_count AS pending_fx_count_change,
       CASE WHEN previous_inflow <> 0 THEN ROUND((inflow - previous_inflow) / ABS(previous_inflow) * 100, 2)::text END AS inflow_change_percent,
       CASE WHEN previous_outflow <> 0 THEN ROUND((outflow - previous_outflow) / ABS(previous_outflow) * 100, 2)::text END AS outflow_change_percent,
       CASE WHEN previous_spending <> 0 THEN ROUND((spending - previous_spending) / ABS(previous_spending) * 100, 2)::text END AS spending_change_percent,
       CASE WHEN previous_net_cashflow <> 0 THEN ROUND((net_cashflow - previous_net_cashflow) / ABS(previous_net_cashflow) * 100, 2)::text END AS net_cashflow_change_percent,
       CASE WHEN previous_transaction_count <> 0 THEN ROUND((transaction_count - previous_transaction_count)::numeric / ABS(previous_transaction_count) * 100, 2)::text END AS transaction_count_change_percent,
       CASE WHEN previous_valued_count <> 0 THEN ROUND((valued_count - previous_valued_count)::numeric / ABS(previous_valued_count) * 100, 2)::text END AS valued_count_change_percent,
       CASE WHEN previous_pending_fx_count <> 0 THEN ROUND((pending_fx_count - previous_pending_fx_count)::numeric / ABS(previous_pending_fx_count) * 100, 2)::text END AS pending_fx_count_change_percent
     FROM paired
     CROSS JOIN current_coverage
     CROSS JOIN pending_currency
     ORDER BY ${query.groupBy === 'month' ? 'dimension_id' : `ABS(${orderMetric}) DESC, dimension_label`}
     LIMIT ${add(limit + 1, '::int')}`,
    values
  );
  const visibleRows = result.rows.slice(0, limit);
  const coverage = coverageFromAggregateRows(visibleRows);
  const columns: AskEvidence['columns'] = [
    { key: 'dimension', label: query.groupBy === 'total' ? 'Scope' : query.groupBy, type: 'text' }
  ];
  const metricLabels: Record<string, string> = {
    spending: 'Spending', inflow: 'Inflow', outflow: 'Outflow', net_cashflow: 'Net cash flow',
    transaction_count: 'Transactions', valued_count: 'Valued', pending_fx_count: 'Pending FX'
  };
  for (const metric of query.metrics) {
    columns.push({ key: metric, label: metricLabels[metric]!, type: metric.endsWith('_count') ? 'number' : 'money', ...(metric.endsWith('_count') ? {} : { currency: context.baseCurrency }) });
    if (query.comparison !== 'none') {
      columns.push({ key: `previous_${metric}`, label: `Previous ${metricLabels[metric]}`, type: metric.endsWith('_count') ? 'number' : 'money', ...(metric.endsWith('_count') ? {} : { currency: context.baseCurrency }) });
      columns.push({ key: `${metric}_change`, label: `${metricLabels[metric]} change`, type: metric.endsWith('_count') ? 'number' : 'money', ...(metric.endsWith('_count') ? {} : { currency: context.baseCurrency }) });
      columns.push({ key: `${metric}_change_percent`, label: `${metricLabels[metric]} change %`, type: 'percentage' });
    }
  }
  const rows = visibleRows.map((row) => {
    const item: Record<string, string | number | boolean | null> = { dimension: row.dimension_label };
    for (const metric of query.metrics) {
      item[metric] = row[metric as keyof AggregateRow] as string | number | null;
      if (query.comparison !== 'none') {
        item[`previous_${metric}`] = row[`previous_${metric}` as keyof AggregateRow] as string | number | null;
        item[`${metric}_change`] = row[`${metric}_change` as keyof AggregateRow] as string | number | null;
        item[`${metric}_change_percent`] = row[`${metric}_change_percent` as keyof AggregateRow] as string | number | null;
      }
    }
    return item;
  });
  const evidence: AskEvidence = {
    id: `e-${query.id}`,
    queryId: query.id,
    title: `${query.groupBy === 'total' ? 'Ledger total' : `${query.groupBy} breakdown`} · ${range.from} to ${range.to}`,
    kind: query.groupBy === 'total' ? 'metric' : query.groupBy === 'month' ? 'line' : 'bar',
    columns,
    rows,
    coverage,
    truncated: result.rows.length > limit,
    drilldownPath: '/transactions'
  };
  const facts: Omit<AskFact, 'id'>[] = visibleRows.slice(0, 20).map((row) => {
    const valuesText = query.metrics.map((metric) => {
      const value = row[metric as keyof AggregateRow];
      const rendered = metric.endsWith('_count') ? String(value) : `${context.baseCurrency} ${String(value)}`;
      const previous = query.comparison === 'none' ? null : row[`previous_${metric}` as keyof AggregateRow];
      const change = query.comparison === 'none' ? null : row[`${metric}_change` as keyof AggregateRow];
      const changePercent = query.comparison === 'none' ? null : row[`${metric}_change_percent` as keyof AggregateRow];
      return previous === null || previous === undefined
        ? `${metricLabels[metric]} ${rendered}`
        : `${metricLabels[metric]} ${rendered}; previous ${metric.endsWith('_count') ? String(previous) : `${context.baseCurrency} ${String(previous)}`}; change ${metric.endsWith('_count') ? String(change) : `${context.baseCurrency} ${String(change)}`}${changePercent === null || changePercent === undefined ? '' : ` (${String(changePercent)}%)`}`;
    }).join(', ');
    return { role: query.comparison === 'none' ? 'summary' : 'comparison', dataset: 'aggregate' as const, text: `${factExcerpt(row.dimension_label, 120)}: ${valuesText}.` };
  });
  return { evidence, facts, coverage };
}

function insightSpecBase(query: AskQueryV1, market: AskMarket, entity: ResolvedEntity | undefined, range: ResolvedAskRange) {
  return {
    range: 'all' as const,
    from: range.from,
    to: range.to,
    ...(market === 'ALL' ? {} : { market }),
    ...(entity?.kind === 'account' ? { accountId: entity.id } : {}),
    ...(entity?.kind === 'category' ? { categoryId: entity.id } : {}),
    ...(entity?.kind === 'merchant' ? { merchantId: entity.id } : {})
  };
}

function coverageFromInsight(value: { status: 'complete' | 'partial'; valuedTransactionCount: number; unvaluedTransactionCount: number; unvaluedByCurrency: Array<{ currency: string; transactionCount: number }> }): AskCoverage {
  return {
    status: value.status,
    valuedTransactionCount: value.valuedTransactionCount,
    pendingFxCount: value.unvaluedTransactionCount,
    pendingByCurrency: value.unvaluedByCurrency.map(({ currency, transactionCount }) => ({ currency, transactionCount }))
  };
}

function partialCoverageWarning(dataset: AskQueryV1['dataset'], title: string, baseCurrency: string) {
  if (dataset === 'transactions') {
    return `${title} includes pending-FX rows whose ${baseCurrency} reporting amounts are unavailable.`;
  }
  if (dataset === 'fx') {
    return `${title} includes rows with missing FX reference evidence, so cost estimates are incomplete.`;
  }
  return `${title} excludes transactions awaiting ${baseCurrency} valuation from monetary calculations.`;
}

async function executeSeasonality(client: PoolClient, query: Extract<AskQueryV1, { dataset: 'seasonality' }>, market: AskMarket, entity: ResolvedEntity | undefined, range: ResolvedAskRange, context: AskAnalyticsContext) {
  const response = await readInsightSeasonality(
    insightSpecBase(query, market, entity, range) as InsightSeasonalityQuery,
    client,
    { asOfDate: context.asOfDate, sourceWatermark: context.sourceWatermark }
  );
  const coverage = coverageFromInsight(response.coverage);
  const evidence: AskEvidence = {
    id: `e-${query.id}`, queryId: query.id, title: `Month-of-year seasonality · ${range.from} to ${range.to}`,
    kind: 'bar',
    columns: [
      { key: 'month', label: 'Month', type: 'text' },
      { key: 'averageSpending', label: 'Average spending', type: 'money', currency: response.baseCurrency },
      { key: 'medianSpending', label: 'Median spending', type: 'money', currency: response.baseCurrency },
      { key: 'observationCount', label: 'Observations', type: 'number' }
    ],
    rows: response.months.map((month) => ({ month: month.monthName, averageSpending: month.averageSpending, medianSpending: month.medianSpending, observationCount: month.observationCount })),
    coverage, truncated: false
  };
  const facts: Omit<AskFact, 'id'>[] = response.status === 'insufficient_history'
    ? [{ role: 'coverage', dataset: 'seasonality', text: `Seasonality needs 12 months of history; ${response.historyMonths} months are available.` }]
    : response.months.slice(0, 12).map((month) => ({ role: 'trend', dataset: 'seasonality' as const, text: `${month.monthName}: average spending ${response.baseCurrency} ${month.averageSpending}, median ${response.baseCurrency} ${month.medianSpending}, across ${month.observationCount} observations.` }));
  return { evidence, facts, coverage };
}

async function executeRecurring(client: PoolClient, query: Extract<AskQueryV1, { dataset: 'recurring' }>, market: AskMarket, entity: ResolvedEntity | undefined, range: ResolvedAskRange, context: AskAnalyticsContext) {
  const matching = [];
  let page = 1;
  let totalPages = 1;
  let response: Awaited<ReturnType<typeof readInsightRecurring>> | undefined;
  do {
    const spec = {
      ...insightSpecBase(query, market, entity, range),
      status: query.status,
      cadence: query.cadence,
      page,
      pageSize: 100
    } as InsightRecurringQuery;
    response = await readInsightRecurring(spec, client, { asOfDate: context.asOfDate });
    totalPages = response.totalPages;
    matching.push(...response.series.filter((series) =>
      (query.direction === undefined || series.direction === query.direction)
      && (query.overdue === undefined || series.overdue === query.overdue)
      && (
        query.priceChanged === undefined
        || (
          series.latestChangePercent !== null
          && !/^[+-]?0+(?:\.0+)?$/.test(series.latestChangePercent)
        ) === query.priceChanged
      )
    ));
    page += 1;
  } while (matching.length <= query.limit && page <= totalPages);
  const filtered = matching.slice(0, query.limit);
  const coverage = coverageFromInsight(await readInsightCoverage(
    insightSpecBase(query, market, entity, range),
    range,
    client,
    context.sourceWatermark
  ));
  const evidence: AskEvidence = {
    id: `e-${query.id}`, queryId: query.id, title: `Recurring activity · ${range.from} to ${range.to}`,
    kind: 'list',
    columns: [
      { key: 'merchant', label: 'Merchant', type: 'text' },
      { key: 'cadence', label: 'Cadence', type: 'status' },
      { key: 'direction', label: 'Direction', type: 'status' },
      { key: 'status', label: 'Status', type: 'status' },
      { key: 'expectedCurrency', label: 'Expected currency', type: 'status' },
      { key: 'expectedAmount', label: 'Expected amount', type: 'money' },
      { key: 'latestChangePercent', label: 'Latest price change', type: 'percentage' },
      { key: 'occurrenceCount', label: 'Occurrences', type: 'number' },
      { key: 'occurrenceEvidence', label: 'Recent occurrence evidence', type: 'text' },
      { key: 'expectedNextDate', label: 'Expected next', type: 'date' },
      { key: 'overdue', label: 'Overdue', type: 'status' }
    ],
    rows: filtered.map((series) => ({
      id: series.id,
      merchant: series.merchantName,
      cadence: series.cadence,
      direction: series.direction,
      status: series.status,
      expectedCurrency: series.currency,
      expectedAmount: series.expectedAmount,
      latestChangePercent: series.latestChangePercent,
      occurrenceCount: series.occurrenceCount,
      occurrenceEvidence: series.occurrences.slice(-query.occurrenceLimit).map((occurrence) => `${occurrence.bookedDate} · ${occurrence.currency} ${occurrence.amount}`).join('; '),
      expectedNextDate: series.expectedNextDate,
      overdue: series.overdue
    })),
    coverage, truncated: matching.length > query.limit, drilldownPath: '/insights?tab=recurring'
  };
  const facts: Omit<AskFact, 'id'>[] = filtered.map((series) => ({
    role: 'evidence',
    dataset: 'recurring' as const,
    text: `${factExcerpt(series.merchantName, 120)}: ${series.cadence} ${series.direction}, expected ${series.currency} ${series.expectedAmount}, status ${series.status}${series.overdue ? ', overdue' : ''}, ${series.occurrenceCount} occurrences${series.latestChangePercent === null ? '' : `, latest price change ${series.latestChangePercent}%`}.`
  }));
  return { evidence, facts, coverage };
}

async function executeFindings(client: PoolClient, query: Extract<AskQueryV1, { dataset: 'findings' }>, market: AskMarket, entity: ResolvedEntity | undefined, range: ResolvedAskRange, context: AskAnalyticsContext) {
  const spec = {
    ...insightSpecBase(query, market, entity, range),
    type: query.type, status: query.status, severity: query.severity, page: 1, pageSize: query.limit
  } as InsightFindingsQuery;
  const response = await readInsightFindings(spec, client);
  const coverage = coverageFromInsight(await readInsightCoverage(
    insightSpecBase(query, market, entity, range),
    range,
    client,
    context.sourceWatermark
  ));
  if (query.mode === 'count') {
    const evidence: AskEvidence = {
      id: `e-${query.id}`,
      queryId: query.id,
      title: `Finding count · ${range.from} to ${range.to}`,
      kind: 'metric',
      columns: [{ key: 'count', label: 'Matching findings', type: 'number' }],
      rows: [{ count: response.total }],
      coverage,
      truncated: false,
      drilldownPath: '/insights?tab=findings'
    };
    return {
      evidence,
      facts: [{ role: 'summary' as const, dataset: 'findings' as const, text: `${response.total} findings match the requested filters.` }],
      coverage
    };
  }
  const evidence: AskEvidence = {
    id: `e-${query.id}`, queryId: query.id, title: `Findings · ${range.from} to ${range.to}`,
    kind: 'list',
    columns: [
      { key: 'title', label: 'Finding', type: 'text' }, { key: 'type', label: 'Type', type: 'status' },
      { key: 'severity', label: 'Severity', type: 'status' }, { key: 'status', label: 'Status', type: 'status' },
      { key: 'summary', label: 'Evidence summary', type: 'text' }
    ],
    rows: response.findings.map((finding) => ({ id: finding.id, title: finding.title, type: finding.type, severity: finding.severity, status: finding.status, summary: finding.summary })),
    coverage, truncated: response.total > response.findings.length, drilldownPath: '/insights?tab=findings'
  };
  const facts: Omit<AskFact, 'id'>[] = response.findings.map((finding) => ({ role: 'evidence', dataset: 'findings' as const, text: `${finding.severity} ${finding.type} finding: ${factExcerpt(finding.title, 120)}. Status ${finding.status}. ${factExcerpt(finding.summary, 240)}` }));
  return { evidence, facts, coverage };
}

type FxRow = QueryResultRow & {
  transaction_id: string; account_name: string; booked_date: string; description_raw: string;
  foreign_amount: string | null; foreign_currency: string | null; charged_amount_native: string;
  native_currency: string; bank_applied_rate: string | null; market_rate: string | null;
  market_rate_date: string | null; market_rate_source: string | null; markup_percent: string | null;
  explicit_fee_native: string; missing_rate: boolean;
  explicit_fee_base: string | null; estimated_markup_base: string | null; base_currency: string;
  total_explicit_fee_base: string; total_estimated_markup_base: string; total_fx_cost_base: string;
  missing_rate_count: number; total_row_count: number; missing_rate_by_currency: unknown;
};

async function executeFx(client: PoolClient, query: Extract<AskQueryV1, { dataset: 'fx' }>, market: AskMarket, entity: ResolvedEntity | undefined, range: ResolvedAskRange, context: AskAnalyticsContext) {
  const built = buildFxAnalyticsQuery({
    from: range.from, to: range.to,
    ...(market === 'ALL' ? {} : { market }),
    ...(entity?.kind === 'account' ? { accountId: entity.id } : {})
  }, undefined, {
    ...(context.sourceWatermark ? { sourceWatermark: context.sourceWatermark } : {}),
    ...(context.fxRateCutoff ? { rateCutoff: context.fxRateCutoff } : {}),
    ...(entity?.kind === 'category' ? { categoryId: entity.id } : {}),
    ...(entity?.kind === 'merchant' ? { merchantId: entity.id } : {}),
    limit: query.mode === 'summary' ? 1 : query.limit + 1
  });
  const result = await client.query<FxRow>(built.text, built.values);
  let rows: Array<Record<string, string | number | boolean | null>>;
  let columns: AskEvidence['columns'];
  if (query.mode === 'summary') {
    const first = result.rows[0];
    rows = first
      ? [{
          explicitFees: first.total_explicit_fee_base,
          estimatedMarkup: first.total_estimated_markup_base,
          totalFxCost: first.total_fx_cost_base,
          missingRateCount: first.missing_rate_count
        }]
      : [];
    columns = [
      { key: 'explicitFees', label: 'Explicit fees', type: 'money', currency: context.baseCurrency },
      { key: 'estimatedMarkup', label: 'Estimated markup', type: 'money', currency: context.baseCurrency },
      { key: 'totalFxCost', label: 'Total FX cost', type: 'money', currency: context.baseCurrency },
      { key: 'missingRateCount', label: 'Missing rates', type: 'number' }
    ];
  } else {
    rows = result.rows.slice(0, query.limit).map((row) => ({
      id: row.transaction_id,
      date: row.booked_date,
      account: row.account_name,
      description: row.description_raw,
      foreignCurrency: row.foreign_currency,
      foreignAmount: row.foreign_amount,
      chargedCurrency: row.native_currency,
      chargedAmount: row.charged_amount_native,
      bankRate: row.bank_applied_rate,
      marketRate: row.market_rate,
      marketRateDate: row.market_rate_date,
      rateSource: row.market_rate_source,
      rateStatus: row.missing_rate ? 'missing_rate' : 'available',
      explicitFee: row.explicit_fee_base,
      estimatedMarkup: row.estimated_markup_base,
      markupPercent: row.markup_percent
    }));
    columns = [
      { key: 'date', label: 'Date', type: 'date' }, { key: 'account', label: 'Account', type: 'text' },
      { key: 'description', label: 'Description', type: 'text' },
      { key: 'chargedCurrency', label: 'Posted currency', type: 'status' },
      { key: 'chargedAmount', label: 'Posted amount', type: 'money' },
      { key: 'foreignCurrency', label: 'Foreign currency', type: 'status' },
      { key: 'foreignAmount', label: 'Foreign amount', type: 'money' },
      { key: 'bankRate', label: 'Bank rate', type: 'decimal' },
      { key: 'marketRate', label: 'Reference rate', type: 'decimal' },
      { key: 'marketRateDate', label: 'Rate date', type: 'date' },
      { key: 'rateSource', label: 'Rate source', type: 'text' },
      { key: 'rateStatus', label: 'Rate status', type: 'status' },
      { key: 'explicitFee', label: 'Explicit fee', type: 'money', currency: context.baseCurrency },
      { key: 'estimatedMarkup', label: 'Estimated markup', type: 'money', currency: context.baseCurrency },
      { key: 'markupPercent', label: 'Markup', type: 'percentage' }
    ];
  }
  const pending = result.rows[0]?.missing_rate_count ?? 0;
  const total = result.rows[0]?.total_row_count ?? 0;
  const rawPendingCurrencies = result.rows[0]?.missing_rate_by_currency;
  const pendingCurrencyObject = typeof rawPendingCurrencies === 'string'
    ? (() => { try { return JSON.parse(rawPendingCurrencies) as unknown; } catch { return {}; } })()
    : rawPendingCurrencies;
  const pendingByCurrency = pendingCurrencyObject && typeof pendingCurrencyObject === 'object' && !Array.isArray(pendingCurrencyObject)
    ? Object.entries(pendingCurrencyObject as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([currency, transactionCount]) => ({ currency, transactionCount: Number(transactionCount ?? 0) }))
    : [];
  const coverage: AskCoverage = { status: pending > 0 ? 'partial' : 'complete', valuedTransactionCount: Math.max(0, total - pending), pendingFxCount: pending, pendingByCurrency };
  const evidence: AskEvidence = { id: `e-${query.id}`, queryId: query.id, title: `FX cost evidence · ${range.from} to ${range.to}`, kind: query.mode === 'summary' ? 'metric' : 'table', columns, rows, coverage, truncated: query.mode === 'evidence' && result.rows.length > query.limit, drilldownPath: '/insights?tab=fx' };
  const first = result.rows[0];
  const facts: Omit<AskFact, 'id'>[] = first ? [{ role: 'summary', dataset: 'fx', text: `Total FX cost ${context.baseCurrency} ${first.total_fx_cost_base}: explicit fees ${context.baseCurrency} ${first.total_explicit_fee_base}, estimated markup ${context.baseCurrency} ${first.total_estimated_markup_base}, with ${first.missing_rate_count} missing-rate rows.` }] : [];
  return { evidence, facts, coverage };
}

type TransactionAskRow = QueryResultRow & {
  id: string; booked_date: string; account_name: string; description: string; merchant_name: string | null;
  category_name: string | null; amount_native: string; currency_native: string; amount_base: string | null;
  currency_base: string; direction: string;
  total_valued_count: string | number;
  total_pending_fx_count: string | number;
  total_pending_by_currency: unknown;
};

async function executeTransactions(client: PoolClient, query: Extract<AskQueryV1, { dataset: 'transactions' }>, market: AskMarket, entity: ResolvedEntity | undefined, range: ResolvedAskRange, context: AskAnalyticsContext) {
  const values: unknown[] = [];
  const add = (value: unknown, cast = '') => { values.push(value); return `$${values.length}${cast}`; };
  const filters = [`t.booked_date BETWEEN ${add(range.from, '::date')} AND ${add(range.to, '::date')}`];
  const scoped = marketCode(market);
  if (scoped) filters.push(`a.market_code = ${add(scoped)}`);
  if (entity?.kind === 'account') filters.push(`t.account_id = ${add(entity.id)}::uuid`);
  if (entity?.kind === 'category') filters.push(`t.category_id = ${add(entity.id)}::uuid`);
  if (entity?.kind === 'merchant') filters.push(`t.merchant_id = ${add(entity.id)}::uuid`);
  if (query.direction) filters.push(`t.direction = ${add(query.direction)}`);
  if (query.valuationStatus === 'valued') filters.push('t.amount_base IS NOT NULL');
  if (query.valuationStatus === 'pending_fx') filters.push('t.amount_base IS NULL');
  if (query.search) {
    const escaped = query.search.replace(/[\\%_]/g, '\\$&');
    const term = add(`%${escaped}%`);
    filters.push(`(t.description_raw ILIKE ${term} ESCAPE '\\' OR m.canonical_name ILIKE ${term} ESCAPE '\\')`);
  }
  if (context.sourceWatermark) filters.push(`t.updated_at <= ${add(context.sourceWatermark)}::timestamptz`);
  const order = {
    date_desc: 'booked_date DESC, id DESC', date_asc: 'booked_date, id',
    amount_desc: 'ABS(amount_base) DESC NULLS LAST, booked_date DESC, id DESC',
    amount_asc: 'ABS(amount_base) ASC NULLS LAST, booked_date DESC, id DESC'
  }[query.sort];
  const result = await client.query<TransactionAskRow>(
    `WITH selected AS (
       SELECT t.id::text, t.booked_date::text, a.display_name AS account_name,
         t.description_raw AS description, m.canonical_name AS merchant_name, c.name AS category_name,
         t.amount_native::text, t.currency_native, t.amount_base,
         COALESCE(t.currency_base, ${add(context.baseCurrency)}) AS currency_base, t.direction
       FROM txn t JOIN account a ON a.id = t.account_id
       LEFT JOIN merchant m ON m.id = t.merchant_id
       LEFT JOIN category c ON c.id = t.category_id
       WHERE ${filters.join(' AND ')}
     ), coverage AS (
       SELECT
         COUNT(*) FILTER (WHERE amount_base IS NOT NULL)::int AS total_valued_count,
         COUNT(*) FILTER (WHERE amount_base IS NULL)::int AS total_pending_fx_count,
         COALESCE((
           SELECT jsonb_object_agg(currency_native, transaction_count)
           FROM (
             SELECT currency_native, COUNT(*)::int AS transaction_count
             FROM selected
             WHERE amount_base IS NULL
             GROUP BY currency_native
           ) pending
         ), '{}'::jsonb) AS total_pending_by_currency
       FROM selected
     )
     SELECT selected.id, selected.booked_date, selected.account_name, selected.description,
       selected.merchant_name, selected.category_name, selected.amount_native,
       selected.currency_native, selected.amount_base::text, selected.currency_base, selected.direction,
       coverage.total_valued_count, coverage.total_pending_fx_count, coverage.total_pending_by_currency
     FROM selected CROSS JOIN coverage
     ORDER BY ${order} LIMIT ${add(query.limit + 1, '::int')}`,
    values
  );
  const selected = result.rows.slice(0, query.limit);
  const coverage = coverageFromAggregateRows(result.rows);
  const evidence: AskEvidence = {
    id: `e-${query.id}`, queryId: query.id, title: `Supporting transactions · ${range.from} to ${range.to}`,
    kind: 'table',
    columns: [
      { key: 'date', label: 'Date', type: 'date' }, { key: 'account', label: 'Account', type: 'text' },
      { key: 'description', label: 'Description', type: 'text' }, { key: 'merchant', label: 'Merchant', type: 'text' },
      { key: 'category', label: 'Category', type: 'text' },
      { key: 'postedCurrency', label: 'Posted currency', type: 'status' },
      { key: 'postedAmount', label: 'Posted amount', type: 'money' },
      { key: 'reporting', label: 'Reporting amount', type: 'money', currency: context.baseCurrency },
      { key: 'status', label: 'Valuation', type: 'status' }
    ],
    rows: selected.map((row) => ({ id: row.id, date: row.booked_date, account: row.account_name, description: row.description, merchant: row.merchant_name, category: row.category_name, postedCurrency: row.currency_native, postedAmount: row.amount_native, reporting: row.amount_base, status: row.amount_base === null ? 'pending_fx' : 'valued' })),
    coverage, truncated: result.rows.length > query.limit, drilldownPath: '/transactions'
  };
  const facts: Omit<AskFact, 'id'>[] = selected.map((row) => ({ role: 'evidence', dataset: 'transactions' as const, text: `${row.booked_date}: ${factExcerpt(row.description, 180)}, posted ${row.currency_native} ${row.amount_native}${row.amount_base === null ? ', reporting valuation pending' : `, reporting ${row.currency_base} ${row.amount_base}`}.` }));
  return { evidence, facts, coverage };
}

export async function executeAskPlan(
  client: PoolClient,
  plan: AskExecutePlanV1,
  baseContext: AskAnalyticsContext,
  localSelection?: AskLocalClarificationReference
): Promise<AskExecutionResult | AskEntityClarification> {
  if (localSelection && !plan.queries.some((query) => query.id === localSelection.queryId && query.entity)) {
    throw new AskInvalidEntitySelectionError();
  }
  const evidence: AskEvidence[] = [];
  const pendingFacts: Array<Omit<AskFact, 'id'>> = [];
  const resolvedQueries: AskResolvedQuery[] = [];
  const warnings: string[] = [];
  let primaryCoverage = completeCoverage();
  for (const query of plan.queries) {
    if (query.dataset === 'fx' && baseContext.fxRatesChangedSinceGeneration) {
      // FX reference rows are mutable rather than generation-versioned. Refuse
      // to mix a post-publication rate with an older analytics snapshot.
      throw new AskAnalyticsRebuildingError();
    }
    const market = query.market ?? baseContext.market;
    const entityResult = localSelection?.queryId === query.id
      ? await resolveSelectedEntity(client, query, market, localSelection)
      : await resolveEntity(client, query, market, plan);
    if (entityResult && 'prompt' in entityResult) return entityResult;
    const entity = entityResult as ResolvedEntity | undefined;
    const range = await rangeFor(client, query, market, entity, baseContext);
    const resolvedComparison = query.dataset === 'aggregate'
      ? comparisonRange(range, query.comparison)
      : null;
    resolvedQueries.push({
      queryId: query.id,
      dataset: query.dataset,
      market,
      from: range.from,
      to: range.to,
      ...(resolvedComparison
        ? { comparisonFrom: resolvedComparison.from, comparisonTo: resolvedComparison.to }
        : {})
    });
    const result = query.dataset === 'aggregate'
      ? await executeAggregate(client, query, market, entity, range, baseContext)
      : query.dataset === 'seasonality'
        ? await executeSeasonality(client, query, market, entity, range, baseContext)
        : query.dataset === 'recurring'
          ? await executeRecurring(client, query, market, entity, range, baseContext)
          : query.dataset === 'findings'
            ? await executeFindings(client, query, market, entity, range, baseContext)
            : query.dataset === 'fx'
              ? await executeFx(client, query, market, entity, range, baseContext)
              : await executeTransactions(client, query, market, entity, range, baseContext);
    evidence.push(boundedEvidence(result.evidence));
    pendingFacts.push(...result.facts);
    if (evidence.length === 1) primaryCoverage = result.coverage;
    if (result.coverage.status === 'partial') {
      warnings.push(partialCoverageWarning(query.dataset, result.evidence.title, baseContext.baseCurrency));
    }
  }
  if (baseContext.sourceChangedSinceGeneration) {
    warnings.push('The answer is pinned to the published analytics watermark; newer ledger changes await refresh.');
  }
  const facts = pendingFacts.slice(0, 20).map((fact, index) => ({
    ...fact,
    id: `f${index + 1}`,
    text: boundedFactText(fact.text)
  }));
  return {
    evidence,
    facts,
    context: {
      market: baseContext.market,
      baseCurrency: baseContext.baseCurrency,
      asOfDate: baseContext.asOfDate,
      timeZone: baseContext.timeZone,
      analyticsGeneration: baseContext.analyticsGeneration,
      thresholdPolicyVersion: baseContext.thresholdPolicyVersion,
      sourceWatermark: baseContext.sourceWatermark,
      sourceChangedSinceGeneration: baseContext.sourceChangedSinceGeneration,
      coverage: primaryCoverage,
      resolvedQueries
    },
    warnings
  };
}
