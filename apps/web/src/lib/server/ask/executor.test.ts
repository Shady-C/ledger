import { askExecutePlanV1Schema } from '@ledger/shared-types';
import type { PoolClient, QueryResultRow } from 'pg';
import { describe, expect, it } from 'vitest';

import {
  AskAnalyticsRebuildingError,
  AskInvalidEntitySelectionError,
  executeAskPlan,
  readAskAnalyticsContext,
  type AskAnalyticsContext
} from './executor.js';

const context: AskAnalyticsContext = {
  market: 'ALL',
  baseCurrency: 'CAD',
  asOfDate: '2026-07-25',
  timeZone: 'UTC',
  analyticsGeneration: 9,
  thresholdPolicyVersion: 'materiality-v1',
  sourceWatermark: '2026-07-25T08:30:00.000Z',
  sourceChangedSinceGeneration: true,
  coverage: {
    status: 'complete',
    valuedTransactionCount: 0,
    pendingFxCount: 0,
    pendingByCurrency: []
  }
};

function clientReturning(rows: QueryResultRow[]) {
  const calls: Array<{ text: string; values: unknown[] }> = [];
  const client = {
    async query(text: string, values: unknown[] = []) {
      calls.push({ text, values });
      return { rows, command: 'SELECT', rowCount: rows.length, oid: 0, fields: [] };
    }
  } as unknown as PoolClient;
  return { client, calls };
}

function clientReturningSequence(resultSets: QueryResultRow[][]) {
  const calls: Array<{ text: string; values: unknown[] }> = [];
  const client = {
    async query(text: string, values: unknown[] = []) {
      calls.push({ text, values });
      const rows = resultSets.shift() ?? [];
      return { rows, command: 'SELECT', rowCount: rows.length, oid: 0, fields: [] };
    }
  } as unknown as PoolClient;
  return { client, calls };
}

describe('Ask closed SQL compiler', () => {
  it('pins the public context and internal FX cutoff to one published generation', async () => {
    const { client, calls } = clientReturning([{
      base_currency: 'TZS',
      generation: '12',
      threshold_policy_version: 'materiality-v1',
      source_watermark: '2026-07-25T08:00:00.123456Z',
      fx_rate_watermark: '2026-07-25T08:05:00.654321+00:00',
      source_changed: true,
      fx_rates_changed: false
    }]);

    const result = await readAskAnalyticsContext(client, 'TZ', '2026-07-25', 'Africa/Dar_es_Salaam');

    expect(calls).toHaveLength(1);
    expect(calls[0]!.text).toContain('settings.published_generation');
    expect(calls[0]!.text).toContain('MAX(fetched_at) AS latest_rate_at FROM fx_rate');
    expect(calls[0]!.text).toContain("run.result ->> 'fx_rate_watermark'");
    expect(calls[0]!.text).toContain('to_char(');
    expect(calls[0]!.text).not.toContain('run.finished_at');
    const sourceFreshnessSql = calls[0]!.text.slice(
      calls[0]!.text.indexOf('GREATEST('),
      calls[0]!.text.indexOf(') AS source_changed')
    );
    expect(sourceFreshnessSql).not.toContain('latest_rate_at');
    expect(sourceFreshnessSql).toContain('FROM category');
    expect(sourceFreshnessSql).toContain('FROM merchant');
    expect(calls[0]!.values).toEqual([]);
    expect(result).toMatchObject({
      market: 'TZ',
      baseCurrency: 'TZS',
      analyticsGeneration: 12,
      thresholdPolicyVersion: 'materiality-v1',
      sourceWatermark: '2026-07-25T08:00:00.123456Z',
      sourceChangedSinceGeneration: true,
      fxRateCutoff: '2026-07-25T08:05:00.654321+00:00',
      fxRatesChangedSinceGeneration: false
    });
  });

  it('keeps hostile provider/user search, dates, market, and watermark out of SQL text', async () => {
    const hostile = `%_' OR 1=1; DROP TABLE txn; --`;
    const { client, calls } = clientReturning([{
      id: '550e8400-e29b-41d4-a716-446655440000',
      booked_date: '2026-07-03',
      account_name: 'Local account',
      description: 'Local description',
      merchant_name: null,
      category_name: null,
      amount_native: '-10.00',
      currency_native: 'TZS',
      amount_base: null,
      currency_base: 'CAD',
      direction: 'debit',
      total_valued_count: 18,
      total_pending_fx_count: 3,
      total_pending_by_currency: { TZS: 3 }
    }]);
    const plan = askExecutePlanV1Schema.parse({
      version: 1,
      disposition: 'execute',
      queries: [{
        id: 'q1',
        dataset: 'transactions',
        market: 'TZ',
        date: { kind: 'absolute', from: '2026-07-01', to: '2026-07-25' },
        direction: 'debit',
        search: hostile,
        valuationStatus: 'pending_fx',
        sort: 'date_desc',
        limit: 20
      }]
    });

    const result = await executeAskPlan(client, plan, context);
    expect('prompt' in result).toBe(false);
    if ('prompt' in result) return;
    expect(calls).toHaveLength(1);
    const compiled = calls[0]!;
    expect(compiled.text).not.toContain(hostile);
    expect(compiled.text).not.toContain('2026-07-01');
    expect(compiled.text).not.toContain(context.sourceWatermark);
    expect(compiled.text).toContain('ILIKE');
    expect(compiled.text).toContain('t.updated_at <=');
    expect(compiled.text).toMatch(/LIMIT \$\d+::int/);
    expect(compiled.text).not.toContain('LIMIT 21');
    expect(compiled.values).toContain('TZ');
    expect(compiled.values).toContain('2026-07-01');
    expect(compiled.values).toContain(context.sourceWatermark);
    expect(compiled.values).toContain(21);
    expect(compiled.values.some((value) => typeof value === 'string' && value.includes('DROP TABLE'))).toBe(true);
    expect(result.context).toMatchObject({
      analyticsGeneration: 9,
      baseCurrency: 'CAD',
      resolvedQueries: [{
        queryId: 'q1',
        dataset: 'transactions',
        market: 'TZ',
        from: '2026-07-01',
        to: '2026-07-25'
      }]
    });
    expect(result.evidence[0]?.rows).toHaveLength(1);
    expect(result.evidence[0]?.coverage).toEqual({
      status: 'partial',
      valuedTransactionCount: 18,
      pendingFxCount: 3,
      pendingByCurrency: [{ currency: 'TZS', transactionCount: 3 }]
    });
    expect(result.warnings).toContain('The answer is pinned to the published analytics watermark; newer ledger changes await refresh.');
  });

  it.each(['total', 'month', 'account', 'category', 'merchant'] as const)(
    'compiles %s grouping and leaves zero-denominator percentage change null',
    async (groupBy) => {
      const { client, calls } = clientReturning([{
        dimension_id: groupBy === 'month' ? '2026-07-01' : 'dimension-1',
        dimension_label: groupBy === 'month' ? '2026-07' : 'Dimension one',
        inflow: '0.00',
        outflow: '25.00',
        spending: '25.00',
        net_cashflow: '-25.00',
        transaction_count: 2,
        valued_count: 2,
        pending_fx_count: 0,
        pending_by_currency: {},
        total_valued_count: 9,
        total_pending_fx_count: 4,
        total_pending_by_currency: { USD: 4 },
        previous_inflow: '0.00',
        previous_outflow: '0.00',
        previous_spending: '0.00',
        previous_net_cashflow: '0.00',
        previous_transaction_count: 0,
        previous_valued_count: 0,
        previous_pending_fx_count: 0,
        inflow_change: '0.00',
        outflow_change: '25.00',
        spending_change: '25.00',
        net_cashflow_change: '-25.00',
        transaction_count_change: 2,
        valued_count_change: 2,
        pending_fx_count_change: 0,
        inflow_change_percent: null,
        outflow_change_percent: null,
        spending_change_percent: null,
        net_cashflow_change_percent: null,
        transaction_count_change_percent: null,
        valued_count_change_percent: null,
        pending_fx_count_change_percent: null
      }]);
      const plan = askExecutePlanV1Schema.parse({
        version: 1,
        disposition: 'execute',
        queries: [{
          id: 'q1',
          dataset: 'aggregate',
          date: { kind: 'absolute', from: '2026-07-01', to: '2026-07-25' },
          metrics: [
            'spending', 'inflow', 'pending_fx_count'
          ],
          groupBy,
          comparison: 'previous_period',
          limit: 20
        }]
      });
      const result = await executeAskPlan(client, plan, { ...context, sourceChangedSinceGeneration: false });
      expect('prompt' in result).toBe(false);
      if ('prompt' in result) return;
      expect(calls).toHaveLength(1);
      expect(calls[0]!.text).toContain('previous_spending <> 0');
      expect(calls[0]!.text).toContain('UNION ALL');
      expect(calls[0]!.text).toContain('comparison_keys');
      expect(calls[0]!.text).not.toContain('ROW_NUMBER()');
      if (groupBy === 'month') {
        expect(calls[0]!.text).toContain('t.booked_date -');
      }
      expect(calls[0]!.text).toMatch(/LIMIT \$\d+::int/);
      expect(calls[0]!.values).toContain(groupBy === 'month' ? 121 : 21);
      expect(calls[0]!.text).not.toContain('2026-07-01');
      expect(result.evidence[0]?.rows[0]).toMatchObject({
        spending: '25.00',
        previous_spending: '0.00',
        spending_change: '25.00',
        spending_change_percent: null
      });
      expect(result.evidence[0]?.coverage).toEqual({
        status: 'partial',
        valuedTransactionCount: 9,
        pendingFxCount: 4,
        pendingByCurrency: [{ currency: 'USD', transactionCount: 4 }]
      });
    }
  );

  it('orders a bounded grouping by the first requested metric', async () => {
    const { client, calls } = clientReturning([]);
    const plan = askExecutePlanV1Schema.parse({
      version: 1,
      disposition: 'execute',
      queries: [{
        id: 'q1',
        dataset: 'aggregate',
        date: { kind: 'preset', value: 'last_month' },
        metrics: ['pending_fx_count'],
        groupBy: 'category',
        comparison: 'none',
        limit: 5
      }]
    });

    await executeAskPlan(client, plan, { ...context, sourceChangedSinceGeneration: false });
    expect(calls[0]?.text).toContain('ORDER BY ABS(pending_fx_count) DESC');
    expect(calls[0]?.values).toContain(6);
  });

  it('orders comparisons by absolute change so prior-only drivers remain visible', async () => {
    const { client, calls } = clientReturning([]);
    const plan = askExecutePlanV1Schema.parse({
      version: 1,
      disposition: 'execute',
      queries: [{
        id: 'q1',
        dataset: 'aggregate',
        date: { kind: 'preset', value: 'last_month' },
        metrics: ['spending'],
        groupBy: 'category',
        comparison: 'previous_period',
        limit: 5
      }]
    });

    await executeAskPlan(client, plan, { ...context, sourceChangedSinceGeneration: false });
    expect(calls[0]?.text).toContain('COALESCE(current.spending, 0)');
    expect(calls[0]?.text).toContain('COALESCE(previous.spending, 0)');
    expect(calls[0]?.text).toContain('ORDER BY ABS(spending - previous_spending) DESC');
  });

  it('resolves duplicate account labels within the requested scope and offers distinguishable local choices for ALL', async () => {
    const accounts = [
      { id: '550e8400-e29b-41d4-a716-446655440001', label: 'Daily card', market_code: 'CA', qualifier: '•••• 1234' },
      { id: '550e8400-e29b-41d4-a716-446655440002', label: 'Daily card', market_code: 'TZ', qualifier: '•••• 9876' }
    ];
    const duplicatePlan = askExecutePlanV1Schema.parse({
      version: 1,
      disposition: 'execute',
      queries: [{
        id: 'q1', dataset: 'aggregate', market: 'ALL',
        date: { kind: 'preset', value: 'last_month' },
        entity: { kind: 'account', term: 'Daily card' },
        metrics: ['spending'], groupBy: 'total', comparison: 'none', limit: 20
      }]
    });
    const duplicateClient = clientReturning(accounts);
    const clarification = await executeAskPlan(duplicateClient.client, duplicatePlan, context);
    expect('prompt' in clarification).toBe(true);
    if (!('prompt' in clarification)) return;
    expect(clarification.choices.map((choice) => choice.label)).toEqual([
      'Daily card · Canada · •••• 1234',
      'Daily card · Tanzania · •••• 9876'
    ]);
    expect(clarification.choices).toEqual(expect.arrayContaining([
      expect.objectContaining({
        localSelection: expect.objectContaining({ queryId: 'q1', entityToken: expect.stringMatching(/^[a-f0-9]{64}$/) })
      })
    ]));
    expect(JSON.stringify(clarification.choices)).not.toContain(accounts[0]!.id);
    expect(JSON.stringify(clarification.choices)).not.toContain(accounts[1]!.id);

    const selectedChoice = clarification.choices[1]?.localSelection;
    expect(selectedChoice).toBeDefined();
    if (!selectedChoice) return;
    const selectedClient = clientReturningSequence([accounts, []]);
    const selected = await executeAskPlan(selectedClient.client, clarification.plan, context, selectedChoice);
    expect('prompt' in selected).toBe(false);
    expect(selectedClient.calls).toHaveLength(2);
    expect(selectedClient.calls[1]?.values).toContain('550e8400-e29b-41d4-a716-446655440002');

    const staleClient = clientReturningSequence([accounts]);
    await expect(executeAskPlan(staleClient.client, clarification.plan, context, {
      ...selectedChoice,
      entityToken: 'f'.repeat(64)
    })).rejects.toBeInstanceOf(AskInvalidEntitySelectionError);

    const scopedPlan = askExecutePlanV1Schema.parse({
      ...duplicatePlan,
      queries: [{ ...duplicatePlan.queries[0], market: 'TZ' }]
    });
    const scopedClient = clientReturningSequence([accounts, []]);
    const scoped = await executeAskPlan(scopedClient.client, scopedPlan, context);
    expect('prompt' in scoped).toBe(false);
    expect(scopedClient.calls).toHaveLength(2);
    expect(scopedClient.calls[1]?.values).toContain('550e8400-e29b-41d4-a716-446655440002');
  });

  it('bounds locally authored facts even when imported descriptions are very long', async () => {
    const { client } = clientReturning([{
      id: '550e8400-e29b-41d4-a716-446655440000',
      booked_date: '2026-07-03',
      account_name: 'Local account',
      description: 'x'.repeat(2_000),
      merchant_name: null,
      category_name: null,
      amount_native: '-10.00',
      currency_native: 'CAD',
      amount_base: '-10.00',
      currency_base: 'CAD',
      direction: 'debit',
      total_valued_count: 1,
      total_pending_fx_count: 0,
      total_pending_by_currency: {}
    }]);
    const plan = askExecutePlanV1Schema.parse({
      version: 1,
      disposition: 'execute',
      queries: [{
        id: 'q1', dataset: 'transactions', market: 'ALL',
        date: { kind: 'preset', value: 'last_month' }, sort: 'date_desc', limit: 20
      }]
    });
    const result = await executeAskPlan(client, plan, { ...context, sourceChangedSinceGeneration: false });
    expect('prompt' in result).toBe(false);
    if ('prompt' in result) return;
    const fact = result.facts[0]?.text ?? '';
    expect(fact.length).toBeLessThanOrEqual(500);
    expect(fact).toContain(`${'x'.repeat(179)}…`);
    expect(fact).not.toContain('x'.repeat(180));
    const description = result.evidence[0]?.rows[0]?.description;
    expect(description).toHaveLength(500);
    expect(String(description).endsWith('…')).toBe(true);
    expect(result.evidence[0]?.truncated).toBe(true);
  });

  it('returns empty FX evidence for no_data handling instead of fabricating zeros', async () => {
    const { client } = clientReturning([]);
    const plan = askExecutePlanV1Schema.parse({
      version: 1,
      disposition: 'execute',
      queries: [{
        id: 'q1',
        dataset: 'fx',
        date: { kind: 'preset', value: 'last_month' },
        mode: 'summary',
        limit: 20
      }]
    });
    const result = await executeAskPlan(client, plan, {
      ...context,
      sourceChangedSinceGeneration: false,
      fxRateCutoff: '2026-07-25T08:00:00.000Z',
      fxRatesChangedSinceGeneration: false
    });
    expect('prompt' in result).toBe(false);
    if ('prompt' in result) return;
    expect(result.evidence[0]?.rows).toEqual([]);
    expect(result.facts).toEqual([]);
  });

  it('binds category FX filters and the generation-specific rate cutoff', async () => {
    const categoryId = '550e8400-e29b-41d4-a716-446655440001';
    const { client, calls } = clientReturningSequence([
      [{ id: categoryId, label: 'Dining', market_code: null }],
      [{
        total_explicit_fee_base: '2.00',
        total_estimated_markup_base: '3.00',
        total_fx_cost_base: '5.00',
        missing_rate_count: 0,
        total_row_count: 1
      }]
    ]);
    const plan = askExecutePlanV1Schema.parse({
      version: 1,
      disposition: 'execute',
      queries: [{
        id: 'q1',
        dataset: 'fx',
        market: 'TZ',
        date: { kind: 'preset', value: 'last_month' },
        entity: { kind: 'category', term: 'Dining' },
        mode: 'summary',
        limit: 20
      }]
    });
    const result = await executeAskPlan(client, plan, {
      ...context,
      sourceChangedSinceGeneration: false,
      fxRateCutoff: '2026-07-25T08:00:00.000Z',
      fxRatesChangedSinceGeneration: false
    });
    expect(calls).toHaveLength(2);
    expect(calls[1]?.text).toContain('t.category_id =');
    expect(calls[1]?.text).toContain('fetched_at <=');
    expect(calls[1]?.values).toContain(categoryId);
    expect(calls[1]?.values).toContain('2026-07-25T08:00:00.000Z');
    expect('prompt' in result).toBe(false);
    if ('prompt' in result) return;
    expect(result.context).not.toHaveProperty('fxRateCutoff');
    expect(result.context).not.toHaveProperty('fxRatesChangedSinceGeneration');
  });

  it('returns auditable FX rate evidence and missing-rate currencies', async () => {
    const { client } = clientReturning([{
      transaction_id: '550e8400-e29b-41d4-a716-446655440000',
      account_name: 'Travel card',
      booked_date: '2026-07-03',
      description_raw: 'FOREIGN PURCHASE',
      foreign_amount: '100.00',
      foreign_currency: 'USD',
      charged_amount_native: '145.00',
      native_currency: 'CAD',
      bank_applied_rate: '1.450000',
      market_rate: null,
      market_rate_date: null,
      market_rate_source: null,
      markup_percent: null,
      explicit_fee_native: '2.00',
      explicit_fee_base: '2.00',
      estimated_markup_base: null,
      missing_rate: true,
      base_currency: 'CAD',
      total_explicit_fee_base: '2.00',
      total_estimated_markup_base: '0.00',
      total_fx_cost_base: '2.00',
      missing_rate_count: 1,
      total_row_count: 1,
      missing_rate_by_currency: { USD: 1 }
    }]);
    const plan = askExecutePlanV1Schema.parse({
      version: 1,
      disposition: 'execute',
      queries: [{
        id: 'q1', dataset: 'fx', market: 'ALL',
        date: { kind: 'preset', value: 'last_month' }, mode: 'evidence', limit: 20
      }]
    });
    const result = await executeAskPlan(client, plan, {
      ...context,
      sourceChangedSinceGeneration: false,
      fxRateCutoff: '2026-07-25T08:00:00.000Z',
      fxRatesChangedSinceGeneration: false
    });
    expect('prompt' in result).toBe(false);
    if ('prompt' in result) return;
    expect(result.evidence[0]?.rows[0]).toMatchObject({
      foreignCurrency: 'USD',
      foreignAmount: '100.00',
      chargedCurrency: 'CAD',
      chargedAmount: '145.00',
      bankRate: '1.450000',
      marketRate: null,
      marketRateDate: null,
      rateStatus: 'missing_rate'
    });
    expect(result.evidence[0]?.coverage).toEqual({
      status: 'partial',
      valuedTransactionCount: 0,
      pendingFxCount: 1,
      pendingByCurrency: [{ currency: 'USD', transactionCount: 1 }]
    });
    expect(result.warnings[0]).toContain('missing FX reference evidence');
  });

  it('refuses FX reads when reference rates are newer than the published generation', async () => {
    const { client, calls } = clientReturning([]);
    const plan = askExecutePlanV1Schema.parse({
      version: 1,
      disposition: 'execute',
      queries: [{
        id: 'q1',
        dataset: 'fx',
        date: { kind: 'preset', value: 'last_month' },
        mode: 'summary',
        limit: 20
      }]
    });
    await expect(executeAskPlan(client, plan, {
      ...context,
      fxRateCutoff: '2026-07-25T08:00:00.000Z',
      fxRatesChangedSinceGeneration: true
    })).rejects.toBeInstanceOf(AskAnalyticsRebuildingError);
    expect(calls).toHaveLength(0);
  });
});
