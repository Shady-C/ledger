import { z } from 'zod';

export const marketCodeSchema = z.enum(['CA', 'TZ']);
export const marketScopeSchema = z.enum(['ALL', 'CA', 'TZ']);
export const optionalMarketQuerySchema = z.preprocess(
  (value) => value === '' || value === null || value === 'ALL' ? undefined : value,
  marketCodeSchema.optional()
);

export type MarketCode = z.infer<typeof marketCodeSchema>;
export type MarketScope = z.infer<typeof marketScopeSchema>;
