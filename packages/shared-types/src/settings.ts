import { z } from 'zod';

import { currencyCodeSchema } from './primitives.js';
import { marketCodeSchema } from './market.js';

export const settingsResponseSchema = z.object({
  baseCurrency: currencyCodeSchema,
  marketProfile: marketCodeSchema.nullable(),
  updatedAt: z.string().datetime()
});

export const homeCurrencySchema = z.enum(['CAD', 'TZS']);

export const settingsPatchSchema = z
  .object({ marketProfile: marketCodeSchema.nullable() })
  .strict();

export const baseCurrencyChangeSchema = z
  .object({ baseCurrency: homeCurrencySchema, confirmed: z.literal(true) })
  .strict();

export type SettingsResponse = z.infer<typeof settingsResponseSchema>;
export type SettingsPatch = z.infer<typeof settingsPatchSchema>;
export type BaseCurrencyChange = z.infer<typeof baseCurrencyChangeSchema>;
export type HomeCurrency = z.infer<typeof homeCurrencySchema>;
