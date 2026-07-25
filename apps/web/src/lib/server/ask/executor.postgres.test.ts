import type { AskAggregateMetric, AskMarket } from '@ledger/shared-types';
import { askExecutePlanV1Schema } from '@ledger/shared-types';
import pg, { type PoolClient } from 'pg';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import {
  executeAskPlan,
  readAskAnalyticsContext,
  type AskAnalyticsContext,
  type AskExecutionResult
} from './executor.js';

const { Pool } = pg;
const databaseUrl = process.env.LEDGER_ASK_POSTGRES_TEST_URL;
const postgresSuite = databaseUrl ? describe : describe.skip;

const CURRENT_FROM = '2099-07-01';
const CURRENT_TO = '2099-07-30';
const SOURCE_WATERMARK = '2099-09-01T00:00:01.123456Z';
const FIXTURE_UPDATED_AT = '2099-09-01T00:00:00.123456Z';
const POST_WATERMARK_UPDATED_AT = '2099-09-01T00:00:02.123456Z';
const FIXTURE_GENERATION = '8000000000000001';
const DEDUP_PREFIX = 'ask-postgres-executor-v1:';

const ids = {
  institution: 'a5a00000-0000-4000-8000-000000000001',
  caAccount: 'a5a00000-0000-4000-8000-000000000101',
  tzAccount: 'a5a00000-0000-4000-8000-000000000102',
  unassignedAccount: 'a5a00000-0000-4000-8000-000000000103',
  diningCategory: 'a5a00000-0000-4000-8000-000000000201',
  incomeCategory: 'a5a00000-0000-4000-8000-000000000202',
  feeCategory: 'a5a00000-0000-4000-8000-000000000203',
  priorOnlyCategory: 'a5a00000-0000-4000-8000-000000000204',
  grocerMerchant: 'a5a00000-0000-4000-8000-000000000301',
  payrollMerchant: 'a5a00000-0000-4000-8000-000000000302',
  bankMerchant: 'a5a00000-0000-4000-8000-000000000303'
} as const;

const labels = {
  caAccount: '__Ask PostgreSQL Canada account__',
  tzAccount: '__Ask PostgreSQL Tanzania account__',
  unassignedAccount: '__Ask PostgreSQL unassigned account__',
  diningCategory: '__Ask PostgreSQL Dining__',
  incomeCategory: '__Ask PostgreSQL Income__',
  feeCategory: '__Ask PostgreSQL Fees__',
  priorOnlyCategory: '__Ask PostgreSQL Prior-year only__',
  grocerMerchant: '__Ask PostgreSQL Grocer__',
  payrollMerchant: '__Ask PostgreSQL Payroll__',
  bankMerchant: '__Ask PostgreSQL Bank__'
} as const;

const allMetrics: AskAggregateMetric[] = [
  'spending',
  'inflow',
  'outflow',
  'net_cashflow',
  'transaction_count',
  'valued_count',
  'pending_fx_count'
];

type AggregateOptions = {
  market?: AskMarket;
  from?: string;
  to?: string;
  metrics?: AskAggregateMetric[];
  groupBy?: 'total' | 'month' | 'account' | 'category' | 'merchant';
  comparison?: 'none' | 'previous_period' | 'previous_year';
};

type FixtureTransaction = {
  id: string;
  key: string;
  accountId: string;
  bookedDate: string;
  description: string;
  merchantId: string | null;
  categoryId: string | null;
  amountNative: string;
  currencyNative: 'CAD' | 'TZS';
  amountBase: string | null;
  fxRate: string | null;
  direction: 'credit' | 'debit' | 'fee' | 'refund' | 'payment';
  flow: 'income' | 'spend' | 'fee' | 'refund' | 'transfer';
  updatedAt?: string;
};

const fixtureTransactions: FixtureTransaction[] = [
  {
    id: 'a5a00000-0000-4000-8000-000000000515', key: 'previous-year-prior-only-spend',
    accountId: ids.caAccount, bookedDate: '2098-07-16', description: 'Prior-year category spend',
    merchantId: ids.grocerMerchant, categoryId: ids.priorOnlyCategory,
    amountNative: '-8.00', currencyNative: 'CAD', amountBase: '-8.00', fxRate: '1',
    direction: 'debit', flow: 'spend'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000501', key: 'previous-ca-spend',
    accountId: ids.caAccount, bookedDate: '2099-06-10', description: 'Prior spend',
    merchantId: ids.grocerMerchant, categoryId: ids.diningCategory,
    amountNative: '-10.00', currencyNative: 'CAD', amountBase: '-10.00', fxRate: '1',
    direction: 'debit', flow: 'spend'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000502', key: 'previous-tz-pending',
    accountId: ids.tzAccount, bookedDate: '2099-06-20', description: 'Prior pending FX',
    merchantId: ids.grocerMerchant, categoryId: ids.diningCategory,
    amountNative: '-2500.00', currencyNative: 'TZS', amountBase: null, fxRate: null,
    direction: 'debit', flow: 'spend'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000503', key: 'current-ca-income',
    accountId: ids.caAccount, bookedDate: '2099-07-02', description: 'Canada income',
    merchantId: ids.payrollMerchant, categoryId: ids.incomeCategory,
    amountNative: '100.10', currencyNative: 'CAD', amountBase: '100.10', fxRate: '1',
    direction: 'credit', flow: 'income'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000504', key: 'current-ca-spend',
    accountId: ids.caAccount, bookedDate: '2099-07-05', description: 'Canada spend',
    merchantId: ids.grocerMerchant, categoryId: ids.diningCategory,
    amountNative: '-20.01', currencyNative: 'CAD', amountBase: '-20.01', fxRate: '1',
    direction: 'debit', flow: 'spend'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000505', key: 'current-ca-fee',
    accountId: ids.caAccount, bookedDate: '2099-07-07', description: 'Canada fee',
    merchantId: ids.bankMerchant, categoryId: ids.feeCategory,
    amountNative: '-2.34', currencyNative: 'CAD', amountBase: '-2.34', fxRate: '1',
    direction: 'fee', flow: 'fee'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000506', key: 'current-ca-refund',
    accountId: ids.caAccount, bookedDate: '2099-07-08', description: 'Canada refund',
    merchantId: ids.grocerMerchant, categoryId: ids.diningCategory,
    amountNative: '5.55', currencyNative: 'CAD', amountBase: '5.55', fxRate: '1',
    direction: 'refund', flow: 'refund'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000507', key: 'current-ca-transfer',
    accountId: ids.caAccount, bookedDate: '2099-07-09', description: 'Canada transfer',
    merchantId: null, categoryId: null,
    amountNative: '-10.00', currencyNative: 'CAD', amountBase: '-10.00', fxRate: '1',
    direction: 'payment', flow: 'transfer'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000508', key: 'current-tz-income',
    accountId: ids.tzAccount, bookedDate: '2099-07-11', description: 'Tanzania income',
    merchantId: ids.payrollMerchant, categoryId: ids.incomeCategory,
    amountNative: '10000.00', currencyNative: 'TZS', amountBase: '4.00', fxRate: '0.00040000',
    direction: 'credit', flow: 'income'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000509', key: 'current-tz-spend',
    accountId: ids.tzAccount, bookedDate: '2099-07-12', description: 'Tanzania valued spend',
    merchantId: ids.grocerMerchant, categoryId: ids.diningCategory,
    amountNative: '-12345.00', currencyNative: 'TZS', amountBase: '-4.94', fxRate: '0.00040000',
    direction: 'debit', flow: 'spend'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000510', key: 'current-tz-pending',
    accountId: ids.tzAccount, bookedDate: '2099-07-13', description: 'Tanzania pending FX',
    merchantId: ids.grocerMerchant, categoryId: ids.diningCategory,
    amountNative: '-7000.00', currencyNative: 'TZS', amountBase: null, fxRate: null,
    direction: 'debit', flow: 'spend'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000513', key: 'current-unassigned-fee',
    accountId: ids.unassignedAccount, bookedDate: '2099-07-14', description: 'Unassigned market fee',
    merchantId: ids.bankMerchant, categoryId: ids.feeCategory,
    amountNative: '-0.02', currencyNative: 'CAD', amountBase: '-0.02', fxRate: '1',
    direction: 'fee', flow: 'fee'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000514', key: 'post-watermark-sentinel',
    accountId: ids.caAccount, bookedDate: '2099-07-15', description: 'Newer unpublished income',
    merchantId: ids.payrollMerchant, categoryId: ids.incomeCategory,
    amountNative: '9999.99', currencyNative: 'CAD', amountBase: '9999.99', fxRate: '1',
    direction: 'credit', flow: 'income', updatedAt: POST_WATERMARK_UPDATED_AT
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000511', key: 'august-ca-spend',
    accountId: ids.caAccount, bookedDate: '2099-08-03', description: 'August Canada spend',
    merchantId: ids.grocerMerchant, categoryId: ids.diningCategory,
    amountNative: '-1.23', currencyNative: 'CAD', amountBase: '-1.23', fxRate: '1',
    direction: 'debit', flow: 'spend'
  },
  {
    id: 'a5a00000-0000-4000-8000-000000000512', key: 'august-tz-income',
    accountId: ids.tzAccount, bookedDate: '2099-08-04', description: 'August Tanzania income',
    merchantId: ids.payrollMerchant, categoryId: ids.incomeCategory,
    amountNative: '2500.00', currencyNative: 'TZS', amountBase: '1.00', fxRate: '0.00040000',
    direction: 'credit', flow: 'income'
  }
];

let pool: pg.Pool | undefined;
let client: PoolClient | undefined;
let context: AskAnalyticsContext | undefined;
let initialPublishedGeneration: string | null = null;
let transactionOpen = false;

function activeClient() {
  if (!client) throw new Error('PostgreSQL integration client is not initialized');
  return client;
}

function activeContext() {
  if (!context) throw new Error('Ask analytics context is not initialized');
  return context;
}

async function insertFixtures(db: PoolClient) {
  await db.query(`SELECT pg_advisory_xact_lock(hashtext('ledger:ask-executor-postgres-test'))`);

  const migration = await db.query<{ migrated: boolean }>(
    `SELECT EXISTS (
       SELECT 1 FROM schema_migrations WHERE version = '202607240015'
     ) AS migrated`
  );
  if (!migration.rows[0]?.migrated) {
    throw new Error('LEDGER_ASK_POSTGRES_TEST_URL must point to a database migrated through 202607240015');
  }

  const settings = await db.query<{ base_currency: string; published_generation: string | null }>(
    `SELECT ledger.base_currency, analytics.published_generation
     FROM ledger_settings ledger
     JOIN analytics_settings analytics ON analytics.singleton
     WHERE ledger.singleton`
  );
  if (settings.rows[0]?.base_currency !== 'CAD') {
    throw new Error('Ask PostgreSQL executor fixtures require a CAD test ledger');
  }
  initialPublishedGeneration = settings.rows[0].published_generation;

  await db.query(
    `INSERT INTO institution (id, name) VALUES ($1::uuid, $2)`,
    [ids.institution, '__Ask PostgreSQL fixture institution__']
  );
  await db.query(
    `INSERT INTO account (
       id, institution_id, display_name, kind, native_currency, market_code, account_ref_masked
     ) VALUES
       ($1::uuid, $4::uuid, $5, 'chequing', 'CAD', 'CA', '•••• 9101'),
       ($2::uuid, $4::uuid, $6, 'wallet', 'TZS', 'TZ', '•••• 9102'),
       ($3::uuid, $4::uuid, $7, 'chequing', 'CAD', 'CA', '•••• 9103')`,
    [
      ids.caAccount, ids.tzAccount, ids.unassignedAccount, ids.institution,
      labels.caAccount, labels.tzAccount, labels.unassignedAccount
    ]
  );
  // Migration 014 permits preserved legacy unassigned accounts but requires a
  // market on new inserts. Clear this fixture before it has financial rows so
  // ALL behavior is covered without enqueueing a refresh job.
  await db.query(`UPDATE account SET market_code = NULL WHERE id = $1::uuid`, [ids.unassignedAccount]);
  await db.query(
    `INSERT INTO category (id, name, kind) VALUES
       ($1::uuid, $5, 'spend'),
       ($2::uuid, $6, 'income'),
       ($3::uuid, $7, 'fee'),
       ($4::uuid, $8, 'spend')`,
    [
      ids.diningCategory, ids.incomeCategory, ids.feeCategory, ids.priorOnlyCategory,
      labels.diningCategory, labels.incomeCategory, labels.feeCategory, labels.priorOnlyCategory
    ]
  );
  await db.query(
    `INSERT INTO merchant (id, canonical_name, normalized_key) VALUES
       ($1::uuid, $4, 'ask-postgres-grocer'),
       ($2::uuid, $5, 'ask-postgres-payroll'),
       ($3::uuid, $6, 'ask-postgres-bank')`,
    [
      ids.grocerMerchant, ids.payrollMerchant, ids.bankMerchant,
      labels.grocerMerchant, labels.payrollMerchant, labels.bankMerchant
    ]
  );

  for (const row of fixtureTransactions) {
    await db.query(
      `INSERT INTO txn (
         id, account_id, booked_date, description_raw, merchant_id, category_id,
         amount_native, currency_native, amount_base, currency_base, fx_rate,
         fx_rate_date, dedup_hash, direction, enrichment, updated_at
       ) VALUES (
         $1::uuid, $2::uuid, $3::date, $4, $5::uuid, $6::uuid,
         $7::numeric, $8, $9::numeric, 'CAD', $10::numeric,
         $11::date, $12, $13, $14::jsonb, $15::timestamptz
       )`,
      [
        row.id,
        row.accountId,
        row.bookedDate,
        row.description,
        row.merchantId,
        row.categoryId,
        row.amountNative,
        row.currencyNative,
        row.amountBase,
        row.fxRate,
        row.amountBase === null ? null : row.bookedDate,
        `${DEDUP_PREFIX}${row.key}`,
        row.direction,
        JSON.stringify({ categorization: { flow_type: row.flow } }),
        row.updatedAt ?? FIXTURE_UPDATED_AT
      ]
    );
  }

  // Override the identity with a fixed, safe-in-JavaScript generation so the
  // rollback does not even leave a non-transactional sequence gap behind.
  await db.query(
    `INSERT INTO analytics_run (
       generation, mode, status, source_watermark, result, requested_at, started_at, finished_at,
       base_currency, threshold_policy_version
     ) OVERRIDING SYSTEM VALUE VALUES (
       $2::bigint, 'full', 'succeeded', $1::timestamptz,
       jsonb_build_object('fx_rate_watermark', $1::text),
       now(), now(), now(), 'CAD', 'materiality-v1'
     )`,
    [SOURCE_WATERMARK, FIXTURE_GENERATION]
  );
  await db.query(
    `UPDATE analytics_settings SET published_generation = $1::bigint WHERE singleton`,
    [FIXTURE_GENERATION]
  );
}

async function runAggregate(options: AggregateOptions = {}): Promise<AskExecutionResult> {
  const plan = askExecutePlanV1Schema.parse({
    version: 1,
    disposition: 'execute',
    queries: [{
      id: 'q1',
      dataset: 'aggregate',
      ...(options.market ? { market: options.market } : {}),
      date: {
        kind: 'absolute',
        from: options.from ?? CURRENT_FROM,
        to: options.to ?? CURRENT_TO
      },
      metrics: options.metrics ?? allMetrics,
      groupBy: options.groupBy ?? 'total',
      comparison: options.comparison ?? 'none',
      limit: 20
    }]
  });
  const result = await executeAskPlan(activeClient(), plan, activeContext());
  if ('prompt' in result) throw new Error(`Unexpected entity clarification: ${result.prompt}`);
  return result;
}

function rowsByDimension(result: AskExecutionResult) {
  return new Map(result.evidence[0]!.rows.map((row) => [String(row.dimension), row]));
}

postgresSuite('Ask aggregate executor against PostgreSQL', () => {
  beforeAll(async () => {
    pool = new Pool({ connectionString: databaseUrl!, max: 1 });
    client = await pool.connect();
    await client.query('BEGIN ISOLATION LEVEL REPEATABLE READ');
    transactionOpen = true;
    try {
      await insertFixtures(client);
      context = await readAskAnalyticsContext(client, 'ALL', '2099-08-31', 'UTC');
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined);
      transactionOpen = false;
      client.release();
      client = undefined;
      await pool.end();
      pool = undefined;
      throw error;
    }
  }, 30_000);

  afterAll(async () => {
    if (!client || !pool) return;
    try {
      if (transactionOpen) {
        await client.query('ROLLBACK');
        transactionOpen = false;
      }
      const residue = await client.query<{ fixture_count: string; published_generation: string | null }>(
        `SELECT
           (SELECT COUNT(*)::text FROM txn WHERE dedup_hash LIKE $1) AS fixture_count,
           (SELECT published_generation::text FROM analytics_settings WHERE singleton) AS published_generation`,
        [`${DEDUP_PREFIX}%`]
      );
      expect(residue.rows[0]).toEqual({
        fixture_count: '0',
        published_generation: initialPublishedGeneration
      });
    } finally {
      client.release();
      client = undefined;
      await pool.end();
      pool = undefined;
    }
  });

  it('pins execution to a real published CAD analytics generation and detects newer source data', () => {
    expect(activeContext()).toMatchObject({
      market: 'ALL',
      baseCurrency: 'CAD',
      asOfDate: '2099-08-31',
      timeZone: 'UTC',
      thresholdPolicyVersion: 'materiality-v1',
      sourceWatermark: SOURCE_WATERMARK,
      sourceChangedSinceGeneration: true,
      fxRatesChangedSinceGeneration: false
    });
    expect(activeContext().analyticsGeneration).toBe(Number(FIXTURE_GENERATION));
  });

  it.each([
    {
      market: 'ALL' as const,
      row: {
        dimension: 'All activity', spending: '21.76', inflow: '104.10', outflow: '21.76',
        net_cashflow: '82.34', transaction_count: 9, valued_count: 8, pending_fx_count: 1
      },
      coverage: {
        status: 'partial', valuedTransactionCount: 8, pendingFxCount: 1,
        pendingByCurrency: [{ currency: 'TZS', transactionCount: 1 }]
      }
    },
    {
      market: 'CA' as const,
      row: {
        dimension: 'All activity', spending: '16.80', inflow: '100.10', outflow: '16.80',
        net_cashflow: '83.30', transaction_count: 5, valued_count: 5, pending_fx_count: 0
      },
      coverage: {
        status: 'complete', valuedTransactionCount: 5, pendingFxCount: 0, pendingByCurrency: []
      }
    },
    {
      market: 'TZ' as const,
      row: {
        dimension: 'All activity', spending: '4.94', inflow: '4.00', outflow: '4.94',
        net_cashflow: '-0.94', transaction_count: 3, valued_count: 2, pending_fx_count: 1
      },
      coverage: {
        status: 'partial', valuedTransactionCount: 2, pendingFxCount: 1,
        pendingByCurrency: [{ currency: 'TZS', transactionCount: 1 }]
      }
    }
  ])('hand-calculates all seven metrics and coverage for $market', async ({ market, row, coverage }) => {
    const result = await runAggregate({ market });

    expect(result.evidence[0]!.rows).toEqual([row]);
    expect(result.evidence[0]!.coverage).toEqual(coverage);
    expect(result.context.resolvedQueries[0]).toMatchObject({ market, from: CURRENT_FROM, to: CURRENT_TO });
    expect(result.warnings).toContain(
      'The answer is pinned to the published analytics watermark; newer ledger changes await refresh.'
    );
    for (const metric of ['spending', 'inflow', 'outflow', 'net_cashflow'] as const) {
      expect(row[metric]).toMatch(/^-?\d+\.\d{2}$/);
    }
  });

  it('executes the month grouping branch with exact decimal rows', async () => {
    const result = await runAggregate({ groupBy: 'month', from: CURRENT_FROM, to: '2099-08-31' });

    expect(result.evidence[0]!.rows).toEqual([
      {
        dimension: '2099-07', spending: '21.76', inflow: '104.10', outflow: '21.76',
        net_cashflow: '82.34', transaction_count: 9, valued_count: 8, pending_fx_count: 1
      },
      {
        dimension: '2099-08', spending: '1.23', inflow: '1.00', outflow: '1.23',
        net_cashflow: '-0.23', transaction_count: 2, valued_count: 2, pending_fx_count: 0
      }
    ]);
  });

  it('executes the account grouping branch across Canadian and Tanzanian accounts', async () => {
    const rows = rowsByDimension(await runAggregate({ groupBy: 'account' }));

    expect(rows.get(labels.caAccount)).toEqual({
      dimension: labels.caAccount, spending: '16.80', inflow: '100.10', outflow: '16.80',
      net_cashflow: '83.30', transaction_count: 5, valued_count: 5, pending_fx_count: 0
    });
    expect(rows.get(labels.tzAccount)).toEqual({
      dimension: labels.tzAccount, spending: '4.94', inflow: '4.00', outflow: '4.94',
      net_cashflow: '-0.94', transaction_count: 3, valued_count: 2, pending_fx_count: 1
    });
    expect(rows.get(labels.unassignedAccount)).toEqual({
      dimension: labels.unassignedAccount, spending: '0.02', inflow: '0.00', outflow: '0.02',
      net_cashflow: '-0.02', transaction_count: 1, valued_count: 1, pending_fx_count: 0
    });
  });

  it('executes the category grouping branch including uncategorized transfers', async () => {
    const rows = rowsByDimension(await runAggregate({
      groupBy: 'category',
      metrics: ['spending', 'transaction_count', 'valued_count', 'pending_fx_count']
    }));

    expect(rows.get(labels.diningCategory)).toEqual({
      dimension: labels.diningCategory, spending: '19.40', transaction_count: 4,
      valued_count: 3, pending_fx_count: 1
    });
    expect(rows.get(labels.feeCategory)).toEqual({
      dimension: labels.feeCategory, spending: '2.36', transaction_count: 2,
      valued_count: 2, pending_fx_count: 0
    });
    expect(rows.get(labels.incomeCategory)).toEqual({
      dimension: labels.incomeCategory, spending: '0.00', transaction_count: 2,
      valued_count: 2, pending_fx_count: 0
    });
    expect(rows.get('Uncategorized')).toEqual({
      dimension: 'Uncategorized', spending: '0.00', transaction_count: 1,
      valued_count: 1, pending_fx_count: 0
    });
  });

  it('executes the merchant grouping branch including unknown merchants', async () => {
    const rows = rowsByDimension(await runAggregate({
      groupBy: 'merchant',
      metrics: ['spending', 'transaction_count', 'valued_count', 'pending_fx_count']
    }));

    expect(rows.get(labels.grocerMerchant)).toEqual({
      dimension: labels.grocerMerchant, spending: '19.40', transaction_count: 4,
      valued_count: 3, pending_fx_count: 1
    });
    expect(rows.get(labels.bankMerchant)).toEqual({
      dimension: labels.bankMerchant, spending: '2.36', transaction_count: 2,
      valued_count: 2, pending_fx_count: 0
    });
    expect(rows.get(labels.payrollMerchant)).toEqual({
      dimension: labels.payrollMerchant, spending: '0.00', transaction_count: 2,
      valued_count: 2, pending_fx_count: 0
    });
    expect(rows.get('Unknown merchant')).toEqual({
      dimension: 'Unknown merchant', spending: '0.00', transaction_count: 1,
      valued_count: 1, pending_fx_count: 0
    });
  });

  it('maps the previous period into the current month and keeps zero-denominator percentages null', async () => {
    const result = await runAggregate({
      groupBy: 'month',
      metrics: ['inflow', 'spending', 'pending_fx_count'],
      comparison: 'previous_period'
    });

    expect(result.evidence[0]!.rows).toEqual([{
      dimension: '2099-07',
      inflow: '104.10', previous_inflow: '0.00', inflow_change: '104.10', inflow_change_percent: null,
      spending: '21.76', previous_spending: '10.00', spending_change: '11.76', spending_change_percent: '117.60',
      pending_fx_count: 1, previous_pending_fx_count: 1,
      pending_fx_count_change: 0, pending_fx_count_change_percent: '0.00'
    }]);
    expect(result.context.resolvedQueries[0]).toEqual({
      queryId: 'q1', dataset: 'aggregate', market: 'ALL',
      from: CURRENT_FROM, to: CURRENT_TO,
      comparisonFrom: '2099-06-01', comparisonTo: '2099-06-30'
    });
    expect(result.evidence[0]!.coverage).toEqual({
      status: 'partial', valuedTransactionCount: 8, pendingFxCount: 1,
      pendingByCurrency: [{ currency: 'TZS', transactionCount: 1 }]
    });
  });

  it('maps the previous year into the current month and retains prior-only category drivers', async () => {
    const monthly = await runAggregate({
      groupBy: 'month',
      metrics: ['inflow', 'spending', 'pending_fx_count'],
      comparison: 'previous_year'
    });

    expect(monthly.evidence[0]!.rows).toEqual([{
      dimension: '2099-07',
      inflow: '104.10', previous_inflow: '0.00', inflow_change: '104.10', inflow_change_percent: null,
      spending: '21.76', previous_spending: '8.00', spending_change: '13.76', spending_change_percent: '172.00',
      pending_fx_count: 1, previous_pending_fx_count: 0,
      pending_fx_count_change: 1, pending_fx_count_change_percent: null
    }]);
    expect(monthly.context.resolvedQueries[0]).toEqual({
      queryId: 'q1', dataset: 'aggregate', market: 'ALL',
      from: CURRENT_FROM, to: CURRENT_TO,
      comparisonFrom: '2098-07-01', comparisonTo: '2098-07-30'
    });

    const categories = rowsByDimension(await runAggregate({
      groupBy: 'category',
      metrics: ['spending'],
      comparison: 'previous_year'
    }));
    expect(categories.get(labels.priorOnlyCategory)).toEqual({
      dimension: labels.priorOnlyCategory,
      spending: '0.00', previous_spending: '8.00', spending_change: '-8.00',
      spending_change_percent: '-100.00'
    });
    expect(categories.get(labels.diningCategory)).toEqual({
      dimension: labels.diningCategory,
      spending: '19.40', previous_spending: '0.00', spending_change: '19.40',
      spending_change_percent: null
    });
  });
});
