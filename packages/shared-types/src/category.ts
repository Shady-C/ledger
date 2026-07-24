import { z } from 'zod';

import { uuidSchema } from './primitives.js';

export const categoryKindSchema = z.enum(['spend', 'income', 'transfer', 'fee']);

export const categorySummarySchema = z.object({
  id: uuidSchema,
  parentId: uuidSchema.nullable(),
  name: z.string().min(1),
  kind: categoryKindSchema
});

export const categoriesResponseSchema = z.object({
  categories: z.array(categorySummarySchema)
});

export type CategoriesResponse = z.infer<typeof categoriesResponseSchema>;
export type CategoryKind = z.infer<typeof categoryKindSchema>;
export type CategorySummary = z.infer<typeof categorySummarySchema>;
