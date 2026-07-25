import { z } from 'zod';

import {
  currencyCodeSchema,
  decimalStringSchema,
  isoDateSchema,
  positiveDecimalStringSchema,
  uuidSchema
} from './primitives.js';
import { optionalMarketQuerySchema } from './market.js';

const emptyStringToUndefined = (value: unknown) =>
  value === '' || value === null ? undefined : value;

const optionalDate = z.preprocess(emptyStringToUndefined, isoDateSchema.optional());
const optionalUuid = z.preprocess(emptyStringToUndefined, uuidSchema.optional());
const pageSchema = z.preprocess(
  emptyStringToUndefined,
  z.coerce.number().int().min(1).default(1)
);
const pageSizeSchema = z.preprocess(
  emptyStringToUndefined,
  z.coerce.number().int().min(1).max(100).default(25)
);

export const insightRangeSchema = z.enum(['3m', '6m', '12m', '24m', 'all']);
export const insightCoverageStatusSchema = z.enum(['complete', 'partial']);
export const insightSensitivitySchema = z.enum(['low', 'balanced', 'high']);
export const insightDimensionSchema = z.enum(['ledger', 'category', 'merchant', 'account']);
export const recurringCadenceSchema = z.enum([
  'weekly',
  'biweekly',
  'monthly',
  'quarterly',
  'annual'
]);
export const recurringStatusSchema = z.enum(['detected', 'confirmed', 'cancelled', 'ignored']);
export const recurringDirectionSchema = z.enum(['spend', 'income']);
export const recurringComparisonBasisSchema = z.enum(['original', 'native', 'base']);
export const insightFindingStatusSchema = z.enum(['new', 'confirmed', 'dismissed', 'resolved']);
export const insightFindingSeveritySchema = z.enum(['info', 'warning', 'critical']);
export const insightFindingTypeSchema = z.enum([
  'unusual_amount',
  'unusual_frequency',
  'monthly_spike',
  'near_duplicate',
  'recurring_price_increase',
  'recurring_overdue',
  'reconciliation_mismatch',
  'coverage_gap',
  'pending_fx'
]);
export const analyticsRunStatusSchema = z.enum(['queued', 'running', 'succeeded', 'failed']);

const dateRangeRefinement = <T extends z.ZodRawShape>(
  shape: T,
  options: { singleEntityFilter?: boolean } = {}
) =>
  z.object(shape).strict().superRefine((value, context) => {
    const range = value as {
      from?: string;
      to?: string;
      accountId?: string;
      categoryId?: string;
      merchantId?: string;
    };
    if (range.from && range.to && range.from > range.to) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: '`from` must be on or before `to`',
        path: ['from']
      });
    }
    if (
      options.singleEntityFilter
      && [range.accountId, range.categoryId, range.merchantId].filter(Boolean).length > 1
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Use only one account, category, or merchant filter at a time',
        path: ['accountId']
      });
    }
  });

const insightBaseQueryShape = {
  range: z.preprocess(emptyStringToUndefined, insightRangeSchema.default('12m')),
  from: optionalDate,
  to: optionalDate,
  accountId: optionalUuid,
  categoryId: optionalUuid,
  merchantId: optionalUuid,
  market: optionalMarketQuerySchema
};

export const insightSummaryQuerySchema = dateRangeRefinement(insightBaseQueryShape, {
  singleEntityFilter: true
});

export const insightTrendsQuerySchema = dateRangeRefinement({
  ...insightBaseQueryShape,
  groupBy: z.preprocess(emptyStringToUndefined, insightDimensionSchema.default('ledger'))
}, { singleEntityFilter: true });

export const insightSeasonalityQuerySchema = dateRangeRefinement(insightBaseQueryShape, {
  singleEntityFilter: true
});

export const insightRecurringQuerySchema = dateRangeRefinement({
  ...insightBaseQueryShape,
  status: z.preprocess(emptyStringToUndefined, recurringStatusSchema.optional()),
  cadence: z.preprocess(emptyStringToUndefined, recurringCadenceSchema.optional()),
  page: pageSchema,
  pageSize: pageSizeSchema
});

export const insightFindingsQuerySchema = dateRangeRefinement({
  ...insightBaseQueryShape,
  type: z.preprocess(emptyStringToUndefined, insightFindingTypeSchema.optional()),
  status: z.preprocess(emptyStringToUndefined, insightFindingStatusSchema.optional()),
  severity: z.preprocess(emptyStringToUndefined, insightFindingSeveritySchema.optional()),
  page: pageSchema,
  pageSize: pageSizeSchema
});

export const recurringPatchSchema = z
  .object({
    status: z.enum(['confirmed', 'cancelled', 'ignored']).optional(),
    cadence: recurringCadenceSchema.optional(),
    expectedAmount: positiveDecimalStringSchema.optional()
  })
  .strict()
  .refine((value) => Object.keys(value).length > 0, 'At least one recurring-series change is required.');

export const insightFindingPatchSchema = z
  .object({ status: z.enum(['confirmed', 'dismissed', 'resolved']) })
  .strict();

export const insightSettingsPatchSchema = z
  .object({ sensitivity: insightSensitivitySchema })
  .strict();

export const insightRebuildRequestSchema = z
  .object({ mode: z.enum(['incremental', 'full']).default('full') })
  .strict()
  .default({ mode: 'full' });

export const insightDateRangeSchema = z.object({
  from: isoDateSchema,
  to: isoDateSchema
});

export const insightUnvaluedCurrencySchema = z.object({
  currency: currencyCodeSchema,
  transactionCount: z.number().int().nonnegative(),
  amountNative: decimalStringSchema
});

export const insightCoverageSchema = z.object({
  status: insightCoverageStatusSchema,
  valuedTransactionCount: z.number().int().nonnegative(),
  unvaluedTransactionCount: z.number().int().nonnegative(),
  unvaluedByCurrency: z.array(insightUnvaluedCurrencySchema)
});

export const analyticsRunSchema = z.object({
  id: uuidSchema,
  status: analyticsRunStatusSchema,
  mode: z.enum(['incremental', 'full']),
  baseCurrency: currencyCodeSchema,
  thresholdPolicyVersion: z.string().min(1),
  sourceWatermark: z.string().datetime().nullable(),
  affectedPeriodCount: z.number().int().nonnegative(),
  aggregateCount: z.number().int().nonnegative(),
  recurringSeriesCount: z.number().int().nonnegative(),
  findingCount: z.number().int().nonnegative(),
  startedAt: z.string().datetime().nullable(),
  finishedAt: z.string().datetime().nullable(),
  durationMs: z.number().int().nonnegative().nullable(),
  error: z.string().nullable()
});

export const insightTotalsSchema = z.object({
  inflow: decimalStringSchema,
  outflow: decimalStringSchema,
  spending: decimalStringSchema,
  netCashflow: decimalStringSchema
});

export const insightComparisonSchema = z.object({
  current: decimalStringSchema,
  previous: decimalStringSchema,
  change: decimalStringSchema,
  changePercent: decimalStringSchema.nullable()
});

export const insightFindingCountsSchema = z.object({
  new: z.number().int().nonnegative(),
  confirmed: z.number().int().nonnegative(),
  dismissed: z.number().int().nonnegative(),
  resolved: z.number().int().nonnegative(),
  unread: z.number().int().nonnegative()
});

export const insightSummaryResponseSchema = z.object({
  baseCurrency: currencyCodeSchema,
  range: insightDateRangeSchema,
  coverage: insightCoverageSchema,
  totals: insightTotalsSchema,
  spendingMonthOverMonth: insightComparisonSchema.nullable(),
  spendingYearOverYear: insightComparisonSchema.nullable(),
  recurring: z.object({
    activeSeries: z.number().int().nonnegative(),
    overdueSeries: z.number().int().nonnegative(),
    expectedMonthlyAmount: decimalStringSchema
  }),
  findings: insightFindingCountsSchema,
  latestRun: analyticsRunSchema.nullable()
});

export const insightTrendPointSchema = z.object({
  period: isoDateSchema,
  dimensionType: insightDimensionSchema,
  dimensionId: uuidSchema.nullable(),
  dimensionName: z.string().min(1),
  inflow: decimalStringSchema,
  outflow: decimalStringSchema,
  spending: decimalStringSchema,
  netCashflow: decimalStringSchema,
  trailingAverageSpending: decimalStringSchema.nullable(),
  trailingMedianSpending: decimalStringSchema.nullable(),
  monthOverMonth: insightComparisonSchema.nullable(),
  yearOverYear: insightComparisonSchema.nullable(),
  coverageStatus: insightCoverageStatusSchema,
  missingValuationCount: z.number().int().nonnegative()
});

export const insightMoverSchema = z.object({
  dimensionType: z.enum(['category', 'merchant']),
  dimensionId: uuidSchema,
  dimensionName: z.string().min(1),
  currentAmount: decimalStringSchema,
  previousAmount: decimalStringSchema,
  changeAmount: decimalStringSchema,
  changePercent: decimalStringSchema.nullable()
});

export const insightTrendsResponseSchema = z.object({
  baseCurrency: currencyCodeSchema,
  range: insightDateRangeSchema,
  groupBy: insightDimensionSchema,
  coverage: insightCoverageSchema,
  points: z.array(insightTrendPointSchema),
  movers: z.object({ positive: z.array(insightMoverSchema), negative: z.array(insightMoverSchema) })
});

export const seasonalityMonthSchema = z.object({
  month: z.number().int().min(1).max(12),
  monthName: z.string().min(1),
  observationCount: z.number().int().nonnegative(),
  averageSpending: decimalStringSchema,
  medianSpending: decimalStringSchema
});

export const insightSeasonalityResponseSchema = z.object({
  baseCurrency: currencyCodeSchema,
  range: insightDateRangeSchema,
  status: z.enum(['available', 'insufficient_history']),
  historyMonths: z.number().int().nonnegative(),
  requiredHistoryMonths: z.literal(12),
  coverage: insightCoverageSchema,
  months: z.array(seasonalityMonthSchema)
});

export const recurringOccurrenceSchema = z.object({
  id: uuidSchema,
  transactionId: uuidSchema,
  bookedDate: isoDateSchema,
  amount: decimalStringSchema,
  currency: currencyCodeSchema
});

export const recurringSeriesSchema = z.object({
  id: uuidSchema,
  merchantId: uuidSchema.nullable(),
  merchantName: z.string().min(1),
  accountId: uuidSchema.nullable(),
  accountName: z.string().min(1).nullable(),
  direction: recurringDirectionSchema,
  cadence: recurringCadenceSchema,
  status: recurringStatusSchema,
  confidence: decimalStringSchema,
  comparisonBasis: recurringComparisonBasisSchema,
  expectedAmount: decimalStringSchema,
  currency: currencyCodeSchema,
  occurrenceCount: z.number().int().positive(),
  firstOccurrenceDate: isoDateSchema,
  lastOccurrenceDate: isoDateSchema,
  expectedNextDate: isoDateSchema.nullable(),
  overdue: z.boolean(),
  latestChangePercent: decimalStringSchema.nullable(),
  userCorrected: z.boolean(),
  occurrences: z.array(recurringOccurrenceSchema)
});

export const recurringSeriesResponseSchema = z.object({ series: recurringSeriesSchema });

export const insightRecurringResponseSchema = z.object({
  baseCurrency: currencyCodeSchema,
  range: insightDateRangeSchema,
  series: z.array(recurringSeriesSchema),
  page: z.number().int().positive(),
  pageSize: z.number().int().positive(),
  total: z.number().int().nonnegative(),
  totalPages: z.number().int().nonnegative()
});

export const insightFindingSchema = z.object({
  id: uuidSchema,
  type: insightFindingTypeSchema,
  status: insightFindingStatusSchema,
  severity: insightFindingSeveritySchema,
  title: z.string().min(1),
  summary: z.string().min(1),
  accountId: uuidSchema.nullable(),
  accountName: z.string().min(1).nullable(),
  categoryId: uuidSchema.nullable(),
  categoryName: z.string().min(1).nullable(),
  merchantId: uuidSchema.nullable(),
  merchantName: z.string().min(1).nullable(),
  recurringSeriesId: uuidSchema.nullable(),
  detectorFingerprint: z.string().min(1),
  evidence: z.record(z.unknown()),
  firstSeenAt: z.string().datetime(),
  lastSeenAt: z.string().datetime(),
  reviewedAt: z.string().datetime().nullable()
});

export const insightFindingResponseSchema = z.object({ finding: insightFindingSchema });

export const insightFindingsResponseSchema = z.object({
  baseCurrency: currencyCodeSchema,
  findings: z.array(insightFindingSchema),
  page: z.number().int().positive(),
  pageSize: z.number().int().positive(),
  total: z.number().int().nonnegative(),
  totalPages: z.number().int().nonnegative()
});

export const insightSettingsSchema = z.object({
  sensitivity: insightSensitivitySchema,
  updatedAt: z.string().datetime()
});

export const insightSettingsResponseSchema = z.object({
  settings: insightSettingsSchema,
  refresh: z.object({
    jobId: uuidSchema,
    kind: z.literal('analytics_refresh'),
    status: z.enum(['queued', 'claimed'])
  }).optional()
});

export const insightRebuildAcceptedSchema = z.object({
  jobId: uuidSchema,
  kind: z.literal('analytics_refresh'),
  status: z.enum(['queued', 'claimed'])
});

export type InsightRange = z.infer<typeof insightRangeSchema>;
export type InsightSensitivity = z.infer<typeof insightSensitivitySchema>;
export type InsightDimension = z.infer<typeof insightDimensionSchema>;
export type RecurringCadence = z.infer<typeof recurringCadenceSchema>;
export type RecurringStatus = z.infer<typeof recurringStatusSchema>;
export type InsightFindingStatus = z.infer<typeof insightFindingStatusSchema>;
export type InsightFindingSeverity = z.infer<typeof insightFindingSeveritySchema>;
export type InsightFindingType = z.infer<typeof insightFindingTypeSchema>;
export type InsightSummaryQuery = z.infer<typeof insightSummaryQuerySchema>;
export type InsightTrendsQuery = z.infer<typeof insightTrendsQuerySchema>;
export type InsightSeasonalityQuery = z.infer<typeof insightSeasonalityQuerySchema>;
export type InsightRecurringQuery = z.infer<typeof insightRecurringQuerySchema>;
export type InsightFindingsQuery = z.infer<typeof insightFindingsQuerySchema>;
export type RecurringPatch = z.infer<typeof recurringPatchSchema>;
export type InsightFindingPatch = z.infer<typeof insightFindingPatchSchema>;
export type InsightSettingsPatch = z.infer<typeof insightSettingsPatchSchema>;
export type InsightRebuildRequest = z.infer<typeof insightRebuildRequestSchema>;
export type InsightCoverage = z.infer<typeof insightCoverageSchema>;
export type AnalyticsRun = z.infer<typeof analyticsRunSchema>;
export type InsightSummaryResponse = z.infer<typeof insightSummaryResponseSchema>;
export type InsightTrendPoint = z.infer<typeof insightTrendPointSchema>;
export type InsightMover = z.infer<typeof insightMoverSchema>;
export type InsightTrendsResponse = z.infer<typeof insightTrendsResponseSchema>;
export type InsightSeasonalityResponse = z.infer<typeof insightSeasonalityResponseSchema>;
export type RecurringSeries = z.infer<typeof recurringSeriesSchema>;
export type InsightRecurringResponse = z.infer<typeof insightRecurringResponseSchema>;
export type InsightFinding = z.infer<typeof insightFindingSchema>;
export type InsightFindingsResponse = z.infer<typeof insightFindingsResponseSchema>;
export type InsightSettingsResponse = z.infer<typeof insightSettingsResponseSchema>;
export type InsightRebuildAccepted = z.infer<typeof insightRebuildAcceptedSchema>;
