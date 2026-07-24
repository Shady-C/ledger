import { z } from 'zod';

export const uuidSchema = z.string().uuid();
export const isoDateSchema = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, 'Expected a date in YYYY-MM-DD format')
  .refine((value) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!match) return false;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const date = new Date(Date.UTC(year, month - 1, day));
    return (
      date.getUTCFullYear() === year
      && date.getUTCMonth() === month - 1
      && date.getUTCDate() === day
    );
  }, 'Expected a valid calendar date');
export const currencyCodeSchema = z.string().regex(/^[A-Z]{3}$/, 'Expected an ISO 4217 currency code');
export const decimalStringSchema = z
  .string()
  .regex(/^-?\d+(?:\.\d+)?$/, 'Expected an exact decimal string');
export const positiveDecimalStringSchema = decimalStringSchema.refine(
  (value) => !value.startsWith('-') && /[1-9]/.test(value),
  'Expected a positive decimal string'
);

export type CurrencyCode = z.infer<typeof currencyCodeSchema>;
export type DecimalString = z.infer<typeof decimalStringSchema>;
export type IsoDate = z.infer<typeof isoDateSchema>;
