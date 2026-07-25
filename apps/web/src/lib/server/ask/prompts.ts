import type { AskRequest } from '@ledger/shared-types';

const dateSelectorSchema = {
  oneOf: [
    {
      type: 'object',
      properties: {
        kind: { const: 'preset' },
        value: {
          enum: [
            'this_month', 'last_month', 'this_quarter', 'last_quarter', 'year_to_date',
            'last_year', 'last_3_months', 'last_6_months', 'last_12_months',
            'last_24_months', 'all'
          ]
        }
      },
      required: ['kind', 'value'],
      additionalProperties: false
    },
    {
      type: 'object',
      properties: { kind: { const: 'rolling_days' }, days: { type: 'integer', minimum: 1, maximum: 366 } },
      required: ['kind', 'days'],
      additionalProperties: false
    },
    {
      type: 'object',
      properties: {
        kind: { const: 'absolute' },
        from: { type: 'string', format: 'date' },
        to: { type: 'string', format: 'date' }
      },
      required: ['kind', 'from', 'to'],
      additionalProperties: false
    }
  ]
};

const entitySchema = {
  type: 'object',
  properties: {
    kind: { enum: ['account', 'category', 'merchant'] },
    term: { type: 'string', minLength: 1, maxLength: 120 }
  },
  required: ['kind', 'term'],
  additionalProperties: false
};

const common = {
  id: { enum: ['q1', 'q2', 'q3'] },
  market: { enum: ['ALL', 'CA', 'TZ'] },
  date: dateSelectorSchema,
  entity: entitySchema
};

export const askPlannerJsonSchema: Record<string, unknown> = {
  oneOf: [
    {
      type: 'object',
      properties: {
        version: { const: 1 },
        disposition: { const: 'execute' },
        queries: {
          type: 'array',
          minItems: 1,
          maxItems: 3,
          items: {
            oneOf: [
              {
                type: 'object',
                properties: {
                  ...common,
                  dataset: { const: 'aggregate' },
                  metrics: {
                    type: 'array', minItems: 1, maxItems: 7, uniqueItems: true,
                    items: { enum: ['spending', 'inflow', 'outflow', 'net_cashflow', 'transaction_count', 'valued_count', 'pending_fx_count'] }
                  },
                  groupBy: { enum: ['total', 'month', 'account', 'category', 'merchant'] },
                  comparison: { enum: ['none', 'previous_period', 'previous_year'] },
                  limit: { type: 'integer', minimum: 1, maximum: 20 }
                },
                required: ['id', 'dataset', 'market', 'date', 'metrics', 'groupBy', 'comparison', 'limit'],
                additionalProperties: false
              },
              {
                type: 'object',
                properties: { ...common, dataset: { const: 'seasonality' } },
                required: ['id', 'dataset', 'market', 'date'],
                additionalProperties: false
              },
              {
                type: 'object',
                properties: {
                  ...common,
                  dataset: { const: 'recurring' },
                  status: { enum: ['detected', 'confirmed', 'cancelled', 'ignored'] },
                  cadence: { enum: ['weekly', 'biweekly', 'monthly', 'quarterly', 'annual'] },
                  direction: { enum: ['spend', 'income'] },
                  overdue: { type: 'boolean' },
                  priceChanged: { type: 'boolean' },
                  occurrenceLimit: { type: 'integer', minimum: 1, maximum: 5 },
                  limit: { type: 'integer', minimum: 1, maximum: 20 }
                },
                required: ['id', 'dataset', 'market', 'date', 'occurrenceLimit', 'limit'],
                additionalProperties: false
              },
              {
                type: 'object',
                properties: {
                  ...common,
                  dataset: { const: 'findings' },
                  type: { enum: ['unusual_amount', 'unusual_frequency', 'monthly_spike', 'near_duplicate', 'recurring_price_increase', 'recurring_overdue', 'reconciliation_mismatch', 'coverage_gap', 'pending_fx'] },
                  status: { enum: ['new', 'confirmed', 'dismissed', 'resolved'] },
                  severity: { enum: ['info', 'warning', 'critical'] },
                  mode: { enum: ['count', 'list'] },
                  limit: { type: 'integer', minimum: 1, maximum: 20 }
                },
                required: ['id', 'dataset', 'market', 'date', 'mode', 'limit'],
                additionalProperties: false
              },
              {
                type: 'object',
                properties: {
                  ...common,
                  dataset: { const: 'fx' }, mode: { enum: ['summary', 'evidence'] },
                  limit: { type: 'integer', minimum: 1, maximum: 20 }
                },
                required: ['id', 'dataset', 'market', 'date', 'mode', 'limit'],
                additionalProperties: false
              },
              {
                type: 'object',
                properties: {
                  ...common,
                  dataset: { const: 'transactions' },
                  direction: { enum: ['debit', 'credit', 'fee', 'interest', 'payment', 'refund'] },
                  search: { type: 'string', minLength: 1, maxLength: 120 },
                  valuationStatus: { enum: ['valued', 'pending_fx'] },
                  sort: { enum: ['date_desc', 'date_asc', 'amount_desc', 'amount_asc'] },
                  limit: { type: 'integer', minimum: 1, maximum: 20 }
                },
                required: ['id', 'dataset', 'market', 'date', 'sort', 'limit'],
                additionalProperties: false
              }
            ]
          }
        }
      },
      required: ['version', 'disposition', 'queries'],
      additionalProperties: false
    },
    {
      type: 'object',
      properties: {
        version: { const: 1 }, disposition: { const: 'clarify' },
        prompt: { type: 'string', minLength: 1, maxLength: 240 },
        choices: {
          type: 'array',
          maxItems: 5,
          items: {
            type: 'object',
            properties: { label: { type: 'string', minLength: 1, maxLength: 120 } },
            required: ['label'],
            additionalProperties: false
          }
        }
      },
      required: ['version', 'disposition', 'prompt'],
      additionalProperties: false
    },
    {
      type: 'object',
      properties: {
        version: { const: 1 }, disposition: { const: 'unsupported' },
        reasonCode: { enum: ['write_request', 'forecasting', 'financial_advice', 'unsupported_dataset', 'unsupported_currency', 'raw_sql', 'ambiguous_question'] },
        message: { type: 'string', minLength: 1, maxLength: 240 },
        suggestions: { type: 'array', maxItems: 3, items: { type: 'string', minLength: 1, maxLength: 160 } }
      },
      required: ['version', 'disposition', 'reasonCode', 'message'],
      additionalProperties: false
    }
  ]
};

export const askNarratorJsonSchema: Record<string, unknown> = {
  type: 'object',
  properties: {
    blocks: {
      type: 'array', minItems: 1, maxItems: 8,
      items: {
        type: 'object',
        properties: {
          heading: { type: 'string', minLength: 1, maxLength: 120 },
          segments: {
            type: 'array', minItems: 1, maxItems: 20,
            items: {
              oneOf: [
                { type: 'object', properties: { type: { const: 'text' }, text: { type: 'string', minLength: 1, maxLength: 300 } }, required: ['type', 'text'], additionalProperties: false },
                { type: 'object', properties: { type: { const: 'fact_ref' }, ref: { type: 'string', pattern: '^f[0-9]+$' } }, required: ['type', 'ref'], additionalProperties: false }
              ]
            }
          }
        },
        required: ['segments'],
        additionalProperties: false
      }
    }
  },
  required: ['blocks'],
  additionalProperties: false
};

export const plannerSystemPrompt = `Ledger Ask planner. Translate the question into only the supplied closed JSON query plan.
Never output SQL. Never request balances, net worth, imports, reconciliation exploration, forecasts, advice, budgets,
investments, or mutations. Return unsupported for those requests using raw_sql, write_request, forecasting,
financial_advice, unsupported_currency, or unsupported_dataset as the matching stable reason code. Use one entity filter at most for aggregates, and
never group an entity-filtered aggregate by a different entity type. All money is in the active home currency; if the
question explicitly requests another reporting currency, return unsupported_currency. Prefer clarification over guessing.
Always include market on every query, copying activeMarket unless the question explicitly overrides it. A compared aggregate
may contain at most three distinct metrics; an uncompared aggregate may contain at most seven. Recurring queries must set
occurrenceLimit from 1 through 5 and may use priceChanged. Findings queries must select count or list mode. Use at most
three independent queries, with ids q1 through q3. Transaction queries are evidence lists, not aggregate math.`;

export const narratorSystemPrompt = `Ledger Ask narration organizer. You receive only opaque deterministic fact references
and safe semantic roles. Return fact_ref segments, optionally joined only by these exact connective strings:
"Here is what the ledger shows: ", "Supporting evidence: ", "In comparison, ", "Also, ", "Coverage note: ", or " ".
If you include a heading, use only Answer, Summary, Comparison, Evidence, or Coverage. Do not write any other prose,
digits, amounts, dates, percentages, ranks, entity names, currencies, comparisons, or quantitative claims. Every factual
statement must be represented by a supplied fact_ref. Never use markdown or HTML.`;

export function plannerMessage(request: AskRequest, asOfDate: string, timeZone: string, baseCurrency: string) {
  return JSON.stringify({
    question: request.question,
    asOfDate,
    timeZone,
    activeMarket: request.market,
    activeHomeCurrency: baseCurrency,
    history: request.history.map((turn) => ({ question: turn.question, plan: turn.plan }))
  });
}
