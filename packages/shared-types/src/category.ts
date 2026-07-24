import { z } from 'zod';

import { decimalStringSchema, isoDateSchema, uuidSchema } from './primitives.js';

export const categoryKindSchema = z.enum(['spend', 'income', 'transfer', 'fee']);
export const transactionFlowTypeSchema = z.enum(['spend', 'income', 'transfer', 'refund', 'fee']);
export const categorySourceSchema = z.enum([
  'fallback',
  'rule',
  'ai',
  'user_merchant',
  'user_transaction'
]);

export const categorySummarySchema = z.object({
  id: uuidSchema,
  parentId: uuidSchema.nullable(),
  name: z.string().min(1),
  kind: categoryKindSchema,
  archivedAt: z.string().datetime().nullable(),
  isProtected: z.boolean()
});

export const categoriesResponseSchema = z.object({
  categories: z.array(categorySummarySchema)
});

export const categoryCreateSchema = z
  .object({
    parentId: uuidSchema.nullable().optional(),
    name: z.string().trim().min(1).max(120),
    kind: categoryKindSchema
  })
  .strict();

export const categoryPatchSchema = z
  .object({
    parentId: uuidSchema.nullable().optional(),
    name: z.string().trim().min(1).max(120).optional(),
    kind: categoryKindSchema.optional(),
    archived: z.boolean().optional()
  })
  .strict()
  .refine((value) => Object.keys(value).length > 0, 'At least one category field is required');

export const categorizationProposalStatusSchema = z.enum(['pending', 'accepted', 'rejected']);

export const categorizationProposalSchema = z.object({
  id: uuidSchema,
  opaqueKey: uuidSchema,
  merchantId: uuidSchema,
  merchantName: z.string().min(1),
  flowType: transactionFlowTypeSchema,
  proposedCategoryId: uuidSchema.nullable(),
  proposedCategoryName: z.string().min(1).nullable(),
  proposedCategoryKind: categoryKindSchema.nullable(),
  confidence: decimalStringSchema,
  status: categorizationProposalStatusSchema,
  provider: z.string().min(1),
  model: z.string().min(1),
  reviewedAt: z.string().datetime().nullable(),
  createdAt: z.string().datetime()
});

export const categorizationProposalsResponseSchema = z.object({
  proposals: z.array(categorizationProposalSchema)
});

export const unresolvedMerchantFlowSchema = z.object({
  merchantId: uuidSchema,
  merchantName: z.string().min(1),
  flowType: transactionFlowTypeSchema,
  transactionCount: z.number().int().positive(),
  firstSeen: isoDateSchema,
  lastSeen: isoDateSchema
});

export const unresolvedMerchantFlowsResponseSchema = z.object({
  unresolved: z.array(unresolvedMerchantFlowSchema)
});

export const categorizationProposalDecisionSchema = z
  .object({ decision: z.enum(['accept', 'reject']) })
  .strict();

export const categorizationRequestSchema = z
  .object({ mode: z.enum(['incremental', 'backfill']).default('incremental') })
  .strict();

export type CategoriesResponse = z.infer<typeof categoriesResponseSchema>;
export type CategorizationProposal = z.infer<typeof categorizationProposalSchema>;
export type CategorizationProposalDecision = z.infer<typeof categorizationProposalDecisionSchema>;
export type CategorizationRequest = z.infer<typeof categorizationRequestSchema>;
export type CategoryCreate = z.infer<typeof categoryCreateSchema>;
export type CategoryKind = z.infer<typeof categoryKindSchema>;
export type CategoryPatch = z.infer<typeof categoryPatchSchema>;
export type CategorySource = z.infer<typeof categorySourceSchema>;
export type CategorySummary = z.infer<typeof categorySummarySchema>;
export type TransactionFlowType = z.infer<typeof transactionFlowTypeSchema>;
export type UnresolvedMerchantFlow = z.infer<typeof unresolvedMerchantFlowSchema>;
