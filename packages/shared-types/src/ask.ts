import { z } from 'zod';

import {
  currencyCodeSchema,
  decimalStringSchema,
  isoDateSchema,
  uuidSchema
} from './primitives.js';
import {
  insightFindingSeveritySchema,
  insightFindingStatusSchema,
  insightFindingTypeSchema,
  recurringCadenceSchema,
  recurringStatusSchema
} from './insights.js';
import { transactionDirectionSchema } from './transaction.js';

export const askMarketSchema = z.enum(['ALL', 'CA', 'TZ']);

export const askTimeZoneSchema = z.string().trim().min(1).max(64).superRefine((value, context) => {
  try {
    new Intl.DateTimeFormat('en', { timeZone: value }).format(new Date(0));
  } catch {
    context.addIssue({ code: z.ZodIssueCode.custom, message: 'Expected a valid IANA timezone' });
  }
});

export const askDatePresetSchema = z.enum([
  'this_month',
  'last_month',
  'this_quarter',
  'last_quarter',
  'year_to_date',
  'last_year',
  'last_3_months',
  'last_6_months',
  'last_12_months',
  'last_24_months',
  'all'
]);

export const askDateSelectorSchema = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('preset'), value: askDatePresetSchema }).strict(),
  z.object({ kind: z.literal('rolling_days'), days: z.number().int().min(1).max(366) }).strict(),
  z.object({ kind: z.literal('absolute'), from: isoDateSchema, to: isoDateSchema }).strict()
]).superRefine((value, context) => {
  if (value.kind === 'absolute' && value.from > value.to) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['from'],
      message: '`from` must be on or before `to`'
    });
  }
});

export const askEntityFilterSchema = z.object({
  kind: z.enum(['account', 'category', 'merchant']),
  term: z.string().trim().min(1).max(120)
}).strict();

const queryBase = {
  id: z.string().regex(/^q[1-3]$/),
  market: askMarketSchema.optional(),
  date: askDateSelectorSchema,
  entity: askEntityFilterSchema.optional()
};

export const askAggregateMetricSchema = z.enum([
  'spending',
  'inflow',
  'outflow',
  'net_cashflow',
  'transaction_count',
  'valued_count',
  'pending_fx_count'
]);

export const askAggregateQuerySchema = z.object({
  ...queryBase,
  dataset: z.literal('aggregate'),
  metrics: z.array(askAggregateMetricSchema).min(1).max(7),
  groupBy: z.enum(['total', 'month', 'account', 'category', 'merchant']).default('total'),
  comparison: z.enum(['none', 'previous_period', 'previous_year']).default('none'),
  limit: z.number().int().min(1).max(20).default(20)
}).strict().superRefine((value, context) => {
  if (new Set(value.metrics).size !== value.metrics.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['metrics'],
      message: 'Aggregate metrics must be unique'
    });
  }
  if (value.comparison !== 'none' && value.metrics.length > 3) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['metrics'],
      message: 'Compared aggregates support at most three metrics'
    });
  }
  if (value.entity && !['total', 'month', value.entity.kind].includes(value.groupBy)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['groupBy'],
      message: 'An entity-filtered aggregate cannot group by another entity dimension'
    });
  }
});

export const askSeasonalityQuerySchema = z.object({
  ...queryBase,
  dataset: z.literal('seasonality')
}).strict();

export const askRecurringQuerySchema = z.object({
  ...queryBase,
  dataset: z.literal('recurring'),
  status: recurringStatusSchema.optional(),
  cadence: recurringCadenceSchema.optional(),
  direction: z.enum(['spend', 'income']).optional(),
  overdue: z.boolean().optional(),
  priceChanged: z.boolean().optional(),
  occurrenceLimit: z.number().int().min(1).max(5).default(3),
  limit: z.number().int().min(1).max(20).default(20)
}).strict();

export const askFindingsQuerySchema = z.object({
  ...queryBase,
  dataset: z.literal('findings'),
  type: insightFindingTypeSchema.optional(),
  status: insightFindingStatusSchema.optional(),
  severity: insightFindingSeveritySchema.optional(),
  mode: z.enum(['count', 'list']).default('list'),
  limit: z.number().int().min(1).max(20).default(20)
}).strict();

export const askFxQuerySchema = z.object({
  ...queryBase,
  dataset: z.literal('fx'),
  mode: z.enum(['summary', 'evidence']).default('summary'),
  limit: z.number().int().min(1).max(20).default(20)
}).strict();

export const askTransactionsQuerySchema = z.object({
  ...queryBase,
  dataset: z.literal('transactions'),
  direction: transactionDirectionSchema.optional(),
  search: z.string().trim().min(1).max(120).optional(),
  valuationStatus: z.enum(['valued', 'pending_fx']).optional(),
  sort: z.enum(['date_desc', 'date_asc', 'amount_desc', 'amount_asc']).default('date_desc'),
  limit: z.number().int().min(1).max(20).default(20)
}).strict();

export const askQueryV1Schema = z.union([
  askAggregateQuerySchema,
  askSeasonalityQuerySchema,
  askRecurringQuerySchema,
  askFindingsQuerySchema,
  askFxQuerySchema,
  askTransactionsQuerySchema
]);

export const askExecutePlanV1Schema = z.object({
  version: z.literal(1),
  disposition: z.literal('execute'),
  queries: z.array(askQueryV1Schema).min(1).max(3)
}).strict().superRefine((value, context) => {
  const ids = value.queries.map((query) => query.id);
  if (new Set(ids).size !== ids.length) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['queries'], message: 'Query ids must be unique' });
  }
});

export const askPlannerClarificationChoiceSchema = z.object({
  label: z.string().trim().min(1).max(120)
}).strict();

export const askClarifyPlanV1Schema = z.object({
  version: z.literal(1),
  disposition: z.literal('clarify'),
  prompt: z.string().trim().min(1).max(240),
  choices: z.array(askPlannerClarificationChoiceSchema).max(5).optional()
}).strict();

export const askUnsupportedPlanV1Schema = z.object({
  version: z.literal(1),
  disposition: z.literal('unsupported'),
  reasonCode: z.enum([
    'write_request',
    'forecasting',
    'financial_advice',
    'unsupported_dataset',
    'unsupported_currency',
    'raw_sql',
    'ambiguous_question'
  ]),
  message: z.string().trim().min(1).max(240),
  suggestions: z.array(z.string().trim().min(1).max(160)).max(3).optional()
}).strict();

export const askPlanV1Schema = z.union([
  askExecutePlanV1Schema,
  askClarifyPlanV1Schema,
  askUnsupportedPlanV1Schema
]);

export const askHistoryTurnSchema = z.object({
  question: z.string().trim().min(1).max(500),
  plan: askPlanV1Schema
}).strict();

export const askEntityTokenSchema = z.string().regex(/^[a-f0-9]{64}$/);

export const askLocalClarificationReferenceSchema = z.object({
  queryId: z.string().regex(/^q[1-3]$/),
  entityToken: askEntityTokenSchema
}).strict();

export const askLocalClarificationSelectionSchema = z.object({
  plan: askExecutePlanV1Schema,
  queryId: z.string().regex(/^q[1-3]$/),
  entityToken: askEntityTokenSchema
}).strict().superRefine((value, context) => {
  const query = value.plan.queries.find((candidate) => candidate.id === value.queryId);
  if (!query) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['queryId'],
      message: 'Local clarification queryId must identify a query in the supplied execute plan'
    });
  } else if (!query.entity) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['plan'],
      message: 'Local clarification selections require an entity-filtered query'
    });
  }
});

export const askRequestSchema = z.object({
  question: z.string().trim().min(1).max(500),
  market: askMarketSchema,
  timeZone: askTimeZoneSchema,
  history: z.array(askHistoryTurnSchema).max(3).default([]),
  localSelection: askLocalClarificationSelectionSchema.optional()
}).strict();

export const askStatusResponseSchema = z.object({
  enabled: z.boolean(),
  available: z.boolean(),
  reason: z.enum(['disabled', 'missing_configuration', 'invalid_configuration']).nullable()
}).strict();

export const askErrorCodeSchema = z.enum([
  'invalid_request',
  'ask_busy',
  'ask_planning_failed',
  'ask_disabled',
  'ask_provider_unavailable',
  'analytics_rebuilding',
  'ask_timeout'
]);

export const askCoverageSchema = z.object({
  status: z.enum(['complete', 'partial']),
  valuedTransactionCount: z.number().int().nonnegative(),
  pendingFxCount: z.number().int().nonnegative(),
  pendingByCurrency: z.array(z.object({
    currency: currencyCodeSchema,
    transactionCount: z.number().int().nonnegative()
  }).strict())
}).strict();

export const askEvidenceColumnSchema = z.object({
  key: z.string().min(1).max(80),
  label: z.string().min(1).max(120),
  type: z.enum(['text', 'money', 'decimal', 'number', 'date', 'percentage', 'status']),
  currency: currencyCodeSchema.optional()
}).strict();

export const askEvidenceCellSchema = z.union([
  z.string().max(500),
  z.number().finite(),
  z.boolean(),
  z.null()
]);

export const askEvidenceSchema = z.object({
  id: z.string().min(1).max(40),
  queryId: z.string().regex(/^q[1-3]$/),
  title: z.string().min(1).max(160),
  kind: z.enum(['metric', 'table', 'line', 'bar', 'list']),
  columns: z.array(askEvidenceColumnSchema).max(16),
  rows: z.array(z.record(askEvidenceCellSchema)).max(120),
  coverage: askCoverageSchema,
  truncated: z.boolean(),
  drilldownPath: z.string().max(500).optional()
}).strict().superRefine((value, context) => {
  for (const [rowIndex, row] of value.rows.entries()) {
    for (const column of value.columns) {
      const cell = row[column.key];
      if (cell === null || cell === undefined) continue;
      if (column.type === 'money' || column.type === 'decimal' || column.type === 'percentage') {
        if (typeof cell !== 'string' || !decimalStringSchema.safeParse(cell).success) {
          context.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['rows', rowIndex, column.key],
            message: `${column.type} cells must be exact decimal strings`
          });
        }
      }
      if (column.type === 'number' && (typeof cell !== 'number' || !Number.isFinite(cell))) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['rows', rowIndex, column.key],
          message: 'number cells must be finite numbers'
        });
      }
      if (column.type === 'date' && (typeof cell !== 'string' || !isoDateSchema.safeParse(cell).success)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['rows', rowIndex, column.key],
          message: 'date cells must be ISO dates'
        });
      }
    }
  }
});

export const askAnswerSegmentSchema = z.discriminatedUnion('type', [
  z.object({ type: z.literal('text'), text: z.string().min(1).max(500) }).strict(),
  z.object({
    type: z.literal('fact'),
    ref: z.string().regex(/^f\d+$/),
    text: z.string().min(1).max(500)
  }).strict()
]);

export const askAnswerBlockSchema = z.object({
  heading: z.string().min(1).max(120).optional(),
  segments: z.array(askAnswerSegmentSchema).min(1).max(20)
}).strict();

export const askResolvedQuerySchema = z.object({
  queryId: z.string().regex(/^q[1-3]$/),
  dataset: z.enum(['aggregate', 'seasonality', 'recurring', 'findings', 'fx', 'transactions']),
  market: askMarketSchema,
  from: isoDateSchema,
  to: isoDateSchema,
  comparisonFrom: isoDateSchema.optional(),
  comparisonTo: isoDateSchema.optional()
}).strict().superRefine((value, context) => {
  if ((value.comparisonFrom === undefined) !== (value.comparisonTo === undefined)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['comparisonFrom'],
      message: 'Comparison range endpoints must be provided together'
    });
  }
});

export const askResponseContextSchema = z.object({
  market: askMarketSchema,
  baseCurrency: currencyCodeSchema,
  asOfDate: isoDateSchema,
  timeZone: z.string().min(1).max(64),
  analyticsGeneration: z.number().int().positive(),
  thresholdPolicyVersion: z.string().min(1),
  sourceWatermark: z.string().datetime({ offset: true }).nullable(),
  sourceChangedSinceGeneration: z.boolean(),
  coverage: askCoverageSchema,
  resolvedQueries: z.array(askResolvedQuerySchema).min(1).max(3)
}).strict();

export const askAnsweredResponseSchema = z.object({
  kind: z.literal('answered'),
  requestId: uuidSchema,
  plan: askExecutePlanV1Schema,
  answer: z.array(askAnswerBlockSchema).min(1).max(8),
  evidence: z.array(askEvidenceSchema).min(1).max(6),
  context: askResponseContextSchema,
  warnings: z.array(z.string().min(1).max(300)).max(8)
}).strict();

export const askClarificationChoiceSchema = z.object({
  label: z.string().trim().min(1).max(120),
  localSelection: askLocalClarificationReferenceSchema.optional()
}).strict();

const askClarificationResponseObjectSchema = z.object({
  kind: z.literal('clarification_required'),
  requestId: uuidSchema,
  prompt: z.string().min(1).max(240),
  choices: z.array(askClarificationChoiceSchema).max(5),
  plan: askPlanV1Schema.optional()
}).strict();

function validateLocalClarificationChoices(
  value: z.infer<typeof askClarificationResponseObjectSchema>,
  context: z.RefinementCtx
) {
  value.choices.forEach((choice, index) => {
    if (!choice.localSelection) return;
    if (value.plan?.disposition !== 'execute') {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['choices', index, 'localSelection'],
        message: 'Local clarification choices require an execute plan'
      });
      return;
    }
    const query = value.plan.queries.find((candidate) => candidate.id === choice.localSelection?.queryId);
    if (!query?.entity) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['choices', index, 'localSelection', 'queryId'],
        message: 'Local clarification choices must identify an entity-filtered query in the response plan'
      });
    }
  });
}

export const askClarificationResponseSchema = askClarificationResponseObjectSchema
  .superRefine(validateLocalClarificationChoices);

export const askUnsupportedResponseSchema = z.object({
  kind: z.literal('unsupported'),
  requestId: uuidSchema,
  reasonCode: askUnsupportedPlanV1Schema.shape.reasonCode,
  message: z.string().min(1).max(240),
  suggestions: z.array(z.string().min(1).max(160)).max(3)
}).strict();

export const askNoDataResponseSchema = z.object({
  kind: z.literal('no_data'),
  requestId: uuidSchema,
  plan: askExecutePlanV1Schema,
  message: z.string().min(1).max(240),
  context: askResponseContextSchema
}).strict();

export const askResponseSchema = z.discriminatedUnion('kind', [
  askAnsweredResponseSchema,
  askClarificationResponseObjectSchema,
  askUnsupportedResponseSchema,
  askNoDataResponseSchema
]).superRefine((value, context) => {
  if (value.kind !== 'clarification_required') return;
  validateLocalClarificationChoices(value, context);
});

export type AskMarket = z.infer<typeof askMarketSchema>;
export type AskDateSelector = z.infer<typeof askDateSelectorSchema>;
export type AskEntityFilter = z.infer<typeof askEntityFilterSchema>;
export type AskAggregateMetric = z.infer<typeof askAggregateMetricSchema>;
export type AskQueryV1 = z.infer<typeof askQueryV1Schema>;
export type AskExecutePlanV1 = z.infer<typeof askExecutePlanV1Schema>;
export type AskPlanV1 = z.infer<typeof askPlanV1Schema>;
export type AskPlannerClarificationChoice = z.infer<typeof askPlannerClarificationChoiceSchema>;
export type AskLocalClarificationReference = z.infer<typeof askLocalClarificationReferenceSchema>;
export type AskLocalClarificationSelection = z.infer<typeof askLocalClarificationSelectionSchema>;
export type AskClarificationChoice = z.infer<typeof askClarificationChoiceSchema>;
export type AskRequest = z.infer<typeof askRequestSchema>;
export type AskStatusResponse = z.infer<typeof askStatusResponseSchema>;
export type AskErrorCode = z.infer<typeof askErrorCodeSchema>;
export type AskCoverage = z.infer<typeof askCoverageSchema>;
export type AskEvidence = z.infer<typeof askEvidenceSchema>;
export type AskAnswerBlock = z.infer<typeof askAnswerBlockSchema>;
export type AskResolvedQuery = z.infer<typeof askResolvedQuerySchema>;
export type AskResponseContext = z.infer<typeof askResponseContextSchema>;
export type AskResponse = z.infer<typeof askResponseSchema>;
