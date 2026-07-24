import { z } from 'zod';

import { currencyCodeSchema } from './primitives.js';

export const settingsResponseSchema = z.object({
  baseCurrency: currencyCodeSchema,
  updatedAt: z.string().datetime()
});

export const baseCurrencyChangeSchema = z
  .object({ baseCurrency: currencyCodeSchema })
  .strict();

export type SettingsResponse = z.infer<typeof settingsResponseSchema>;
export type BaseCurrencyChange = z.infer<typeof baseCurrencyChangeSchema>;
