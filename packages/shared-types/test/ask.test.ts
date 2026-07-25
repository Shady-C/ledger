import { describe, expect, it } from 'vitest';

import {
  askPlanV1Schema,
  askRequestSchema,
  askResponseContextSchema,
  askResponseSchema,
  askStatusResponseSchema,
  type AskExecutePlanV1,
  type AskQueryV1,
  type AskResponseContext
} from '../src/index.js';

const requestId = '550e8400-e29b-41d4-a716-446655440000';

const commonQuery = {
  id: 'q1' as const,
  date: { kind: 'preset' as const, value: 'last_12_months' as const }
};

const aggregateQuery = {
  ...commonQuery,
  dataset: 'aggregate' as const,
  metrics: ['spending' as const],
  groupBy: 'category' as const,
  comparison: 'previous_period' as const,
  limit: 20
};

const queries: AskQueryV1[] = [
  aggregateQuery,
  { ...commonQuery, dataset: 'seasonality' },
  {
    ...commonQuery,
    dataset: 'recurring',
    status: 'confirmed',
    cadence: 'monthly',
    direction: 'spend',
    overdue: true,
    priceChanged: true,
    occurrenceLimit: 5,
    limit: 20
  },
  {
    ...commonQuery,
    dataset: 'findings',
    type: 'monthly_spike',
    status: 'new',
    severity: 'warning',
    mode: 'list',
    limit: 20
  },
  { ...commonQuery, dataset: 'fx', mode: 'evidence', limit: 20 },
  {
    ...commonQuery,
    dataset: 'transactions',
    direction: 'debit',
    search: 'groceries',
    valuationStatus: 'valued',
    sort: 'amount_desc',
    limit: 20
  }
];

const executePlan: AskExecutePlanV1 = {
  version: 1,
  disposition: 'execute',
  queries: [aggregateQuery]
};

const entityExecutePlan: AskExecutePlanV1 = {
  version: 1,
  disposition: 'execute',
  queries: [{
    ...aggregateQuery,
    entity: { kind: 'account', term: 'Daily card' },
    groupBy: 'total'
  }]
};

const entityToken = 'a'.repeat(64);

const context: AskResponseContext = {
  market: 'ALL',
  baseCurrency: 'CAD',
  asOfDate: '2026-07-25',
  timeZone: 'Africa/Dar_es_Salaam',
  analyticsGeneration: 7,
  thresholdPolicyVersion: 'materiality-v1',
  sourceWatermark: '2026-07-25T08:30:00.000Z',
  sourceChangedSinceGeneration: false,
  coverage: {
    status: 'complete',
    valuedTransactionCount: 4,
    pendingFxCount: 0,
    pendingByCurrency: []
  },
  resolvedQueries: [{
    queryId: 'q1',
    dataset: 'aggregate',
    market: 'ALL',
    from: '2025-08-01',
    to: '2026-07-25'
  }]
};

const evidence = {
  id: 'e1',
  queryId: 'q1',
  title: 'Spending by category',
  kind: 'bar' as const,
  columns: [
    { key: 'category', label: 'Category', type: 'text' as const },
    { key: 'spending', label: 'Spending', type: 'money' as const, currency: 'CAD' }
  ],
  rows: [{ category: 'Groceries', spending: '125.50' }],
  coverage: context.coverage,
  truncated: false,
  drilldownPath: '/transactions?categoryId=57e68f0d-846d-4f0e-858b-2838992d2bab'
};

describe('AskPlanV1', () => {
  it('accepts every closed query dataset', () => {
    for (const query of queries) {
      expect(askPlanV1Schema.safeParse({
        version: 1,
        disposition: 'execute',
        queries: [query]
      }).success, query.dataset).toBe(true);
    }
  });

  it('accepts all three plan dispositions', () => {
    expect(askPlanV1Schema.safeParse(executePlan).success).toBe(true);
    expect(askPlanV1Schema.safeParse({
      version: 1,
      disposition: 'clarify',
      prompt: 'Which account did you mean?',
      choices: [{ label: 'Daily card' }, { label: 'Travel card' }]
    }).success).toBe(true);
    expect(askPlanV1Schema.safeParse({
      version: 1,
      disposition: 'unsupported',
      reasonCode: 'forecasting',
      message: 'Forecasting is outside Phase 3.',
      suggestions: ['Ask about historical monthly spending.']
    }).success).toBe(true);
  });

  it('keeps planner-authored clarification choices label-only', () => {
    const clarification = {
      version: 1,
      disposition: 'clarify',
      prompt: 'Which account did you mean?'
    };
    expect(askPlanV1Schema.safeParse({
      ...clarification,
      choices: ['Daily card']
    }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({
      ...clarification,
      choices: [{
        label: 'Daily card',
        localSelection: { queryId: 'q1', entityToken }
      }]
    }).success).toBe(false);
  });

  it('enforces version, query-count, id, and strict-key boundaries', () => {
    expect(askPlanV1Schema.safeParse({ ...executePlan, version: 2 }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({ ...executePlan, queries: [] }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [
        aggregateQuery,
        { ...aggregateQuery, id: 'q2' },
        { ...aggregateQuery, id: 'q3' },
        aggregateQuery
      ]
    }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [aggregateQuery, { ...aggregateQuery }]
    }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{ ...aggregateQuery, rawSql: 'DROP TABLE txn' }]
    }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{ ...aggregateQuery, id: 'query-1' }]
    }).success).toBe(false);
  });

  it('bounds ranges, entity terms, row limits, and aggregate intersections', () => {
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{ ...aggregateQuery, date: { kind: 'rolling_days', days: 367 } }]
    }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{
        ...aggregateQuery,
        date: { kind: 'absolute', from: '2026-07-25', to: '2026-07-24' }
      }]
    }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{ ...aggregateQuery, limit: 21 }]
    }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{
        ...aggregateQuery,
        entity: { kind: 'account', term: 'Daily card' },
        groupBy: 'category'
      }]
    }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{
        ...aggregateQuery,
        entity: { kind: 'account', term: 'x'.repeat(121) },
        groupBy: 'total'
      }]
    }).success).toBe(false);
  });

  it('keeps compared aggregate metrics within the sixteen-column evidence budget', () => {
    const allMetrics = [
      'spending',
      'inflow',
      'outflow',
      'net_cashflow',
      'transaction_count',
      'valued_count',
      'pending_fx_count'
    ] as const;
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{ ...aggregateQuery, metrics: allMetrics, comparison: 'none' }]
    }).success).toBe(true);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{ ...aggregateQuery, metrics: allMetrics.slice(0, 3), comparison: 'previous_year' }]
    }).success).toBe(true);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{ ...aggregateQuery, metrics: allMetrics.slice(0, 4), comparison: 'previous_period' }]
    }).success).toBe(false);
    expect(askPlanV1Schema.safeParse({
      ...executePlan,
      queries: [{ ...aggregateQuery, metrics: ['spending', 'spending'], comparison: 'none' }]
    }).success).toBe(false);
  });
});

describe('Ask request and status contracts', () => {
  it('trims questions and applies the in-memory history default', () => {
    expect(askRequestSchema.parse({
      question: '  What changed?  ',
      market: 'ALL',
      timeZone: 'UTC'
    })).toEqual({
      question: 'What changed?',
      market: 'ALL',
      timeZone: 'UTC',
      history: []
    });
  });

  it('allows at most 500 question characters and three prior validated plans', () => {
    const history = Array.from({ length: 3 }, (_, index) => ({
      question: `Earlier ${index}`,
      plan: executePlan
    }));
    expect(askRequestSchema.safeParse({
      question: 'x'.repeat(500),
      market: 'TZ',
      timeZone: 'Africa/Dar_es_Salaam',
      history
    }).success).toBe(true);
    expect(askRequestSchema.safeParse({
      question: 'x'.repeat(501),
      market: 'TZ',
      timeZone: 'Africa/Dar_es_Salaam'
    }).success).toBe(false);
    expect(askRequestSchema.safeParse({
      question: 'Follow up',
      market: 'TZ',
      timeZone: 'Africa/Dar_es_Salaam',
      history: [...history, history[0]]
    }).success).toBe(false);
    expect(askRequestSchema.safeParse({
      question: 'Follow up',
      market: 'TZ',
      timeZone: 'Not/A_TimeZone'
    }).success).toBe(false);
  });

  it('rejects unknown request and history keys', () => {
    expect(askRequestSchema.safeParse({
      question: 'What changed?',
      market: 'ALL',
      timeZone: 'UTC',
      sql: 'SELECT * FROM txn'
    }).success).toBe(false);
    expect(askRequestSchema.safeParse({
      question: 'Follow up',
      market: 'ALL',
      timeZone: 'UTC',
      history: [{ question: 'Earlier', plan: executePlan, answer: 'secret result' }]
    }).success).toBe(false);
  });

  it('strictly binds an opaque local selection to an entity-filtered execute query', () => {
    const selection = {
      plan: entityExecutePlan,
      queryId: 'q1',
      entityToken
    };
    expect(askRequestSchema.safeParse({
      question: 'What did I spend last month?',
      market: 'ALL',
      timeZone: 'UTC',
      localSelection: selection
    }).success).toBe(true);
    expect(askRequestSchema.safeParse({
      question: 'What did I spend last month?',
      market: 'ALL',
      timeZone: 'UTC',
      localSelection: { ...selection, entityToken: 'not-opaque' }
    }).success).toBe(false);
    expect(askRequestSchema.safeParse({
      question: 'What did I spend last month?',
      market: 'ALL',
      timeZone: 'UTC',
      localSelection: { ...selection, queryId: 'q2' }
    }).success).toBe(false);
    expect(askRequestSchema.safeParse({
      question: 'What did I spend last month?',
      market: 'ALL',
      timeZone: 'UTC',
      localSelection: { ...selection, plan: executePlan }
    }).success).toBe(false);
    expect(askRequestSchema.safeParse({
      question: 'What did I spend last month?',
      market: 'ALL',
      timeZone: 'UTC',
      localSelection: { ...selection, label: 'Daily card · Canada · •••• 1234' }
    }).success).toBe(false);
  });

  it('accepts the closed status surface and rejects unknown reasons', () => {
    expect(askStatusResponseSchema.parse({
      enabled: false,
      available: false,
      reason: 'disabled'
    })).toEqual({ enabled: false, available: false, reason: 'disabled' });
    expect(askStatusResponseSchema.safeParse({
      enabled: true,
      available: false,
      reason: 'provider_down'
    }).success).toBe(false);
    expect(askStatusResponseSchema.safeParse({
      enabled: true,
      available: true,
      reason: null,
      model: 'secret-model-name'
    }).success).toBe(false);
  });
});

describe('Ask response contracts', () => {
  it('accepts every semantic response outcome', () => {
    const answered = {
      kind: 'answered',
      requestId,
      plan: executePlan,
      answer: [{
        heading: 'Answer',
        segments: [
          { type: 'text', text: 'Here is what the ledger shows: ' },
          { type: 'fact', ref: 'f1', text: 'Groceries: CAD 125.50' }
        ]
      }],
      evidence: [evidence],
      context,
      warnings: []
    };
    const clarification = {
      kind: 'clarification_required',
      requestId,
      prompt: 'Which account did you mean?',
      choices: [{ label: 'Daily card' }, { label: 'Travel card' }],
      plan: {
        version: 1,
        disposition: 'clarify',
        prompt: 'Which account did you mean?',
        choices: [{ label: 'Daily card' }, { label: 'Travel card' }]
      }
    };
    const unsupported = {
      kind: 'unsupported',
      requestId,
      reasonCode: 'forecasting',
      message: 'Forecasting is outside Phase 3.',
      suggestions: []
    };
    const noData = {
      kind: 'no_data',
      requestId,
      plan: executePlan,
      message: 'No ledger data matched the resolved question.',
      context
    };

    for (const response of [answered, clarification, unsupported, noData]) {
      expect(askResponseSchema.safeParse(response).success, response.kind).toBe(true);
    }
  });

  it('requires local clarification choices to reference the supplied execute plan', () => {
    const localChoice = {
      label: 'Daily card · Canada · •••• 1234',
      localSelection: { queryId: 'q1', entityToken }
    };
    const response = {
      kind: 'clarification_required',
      requestId,
      prompt: 'Which account did you mean?',
      choices: [localChoice],
      plan: entityExecutePlan
    };
    expect(askResponseSchema.safeParse(response).success).toBe(true);
    expect(askResponseSchema.safeParse({ ...response, plan: undefined }).success).toBe(false);
    expect(askResponseSchema.safeParse({ ...response, plan: executePlan }).success).toBe(false);
    expect(askResponseSchema.safeParse({
      ...response,
      choices: [{ ...localChoice, localSelection: { ...localChoice.localSelection, queryId: 'q2' } }]
    }).success).toBe(false);
  });

  it('keeps context strict and bounds resolved query inspection metadata', () => {
    expect(askResponseContextSchema.safeParse({
      ...context,
      sourceWatermark: '2026-07-25T08:30:00.123456Z'
    }).success).toBe(true);
    expect(askResponseContextSchema.safeParse({ ...context, sql: 'SELECT 1' }).success).toBe(false);
    expect(askResponseContextSchema.safeParse({ ...context, resolvedQueries: [] }).success).toBe(false);
    expect(askResponseContextSchema.safeParse({
      ...context,
      resolvedQueries: Array.from({ length: 4 }, (_, index) => ({
        queryId: `q${Math.min(index + 1, 3)}`,
        dataset: 'aggregate',
        market: 'ALL',
        from: '2026-01-01',
        to: '2026-07-25'
      }))
    }).success).toBe(false);
    expect(askResponseContextSchema.safeParse({
      ...context,
      resolvedQueries: [{ ...context.resolvedQueries[0], from: '2026-02-31' }]
    }).success).toBe(false);
    expect(askResponseContextSchema.safeParse({
      ...context,
      resolvedQueries: [{
        ...context.resolvedQueries[0],
        comparisonFrom: '2025-08-01'
      }]
    }).success).toBe(false);
    expect(askResponseContextSchema.safeParse({
      ...context,
      resolvedQueries: [{
        ...context.resolvedQueries[0],
        comparisonFrom: '2024-08-01',
        comparisonTo: '2025-07-25'
      }]
    }).success).toBe(true);
  });

  it('bounds evidence tables, columns, blocks, and response keys', () => {
    const base = {
      kind: 'answered',
      requestId,
      plan: executePlan,
      answer: [{ segments: [{ type: 'fact', ref: 'f1', text: 'CAD 1.00' }] }],
      evidence: [evidence],
      context,
      warnings: []
    };
    expect(askResponseSchema.safeParse({
      ...base,
      evidence: [{ ...evidence, rows: Array.from({ length: 121 }, () => ({ spending: '1.00' })) }]
    }).success).toBe(false);
    expect(askResponseSchema.safeParse({
      ...base,
      evidence: [{ ...evidence, rows: [{ category: 'Groceries', spending: 125.5 }] }]
    }).success).toBe(false);
    expect(askResponseSchema.safeParse({
      ...base,
      evidence: [{
        ...evidence,
        columns: Array.from({ length: 17 }, (_, index) => ({
          key: `c${index}`,
          label: `Column ${index}`,
          type: 'text'
        }))
      }]
    }).success).toBe(false);
    expect(askResponseSchema.safeParse({ ...base, evidence: Array(7).fill(evidence) }).success).toBe(false);
    expect(askResponseSchema.safeParse({
      ...base,
      evidence: [{ ...evidence, rows: [{ category: 'x'.repeat(501), spending: '125.50' }] }]
    }).success).toBe(false);
    expect(askResponseSchema.safeParse({ ...base, prompt: 'hidden extra property' }).success).toBe(false);
  });

  it('does not coerce financial evidence numbers away from exact strings', () => {
    const parsed = askResponseSchema.parse({
      kind: 'answered',
      requestId,
      plan: executePlan,
      answer: [{ segments: [{ type: 'fact', ref: 'f1', text: 'CAD 125.50' }] }],
      evidence: [evidence],
      context,
      warnings: []
    });
    expect(parsed.kind).toBe('answered');
    if (parsed.kind === 'answered') {
      expect(parsed.evidence[0]?.rows[0]?.spending).toBe('125.50');
    }
    expect(askResponseSchema.safeParse({
      kind: 'answered',
      requestId,
      plan: executePlan,
      answer: [{ segments: [{ type: 'fact', ref: 'f1', text: 'Reference rate 1.25' }] }],
      evidence: [{
        ...evidence,
        columns: [{ key: 'rate', label: 'Reference rate', type: 'decimal' }],
        rows: [{ rate: 1.25 }]
      }],
      context,
      warnings: []
    }).success).toBe(false);
  });
});
