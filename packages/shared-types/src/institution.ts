import { z } from 'zod';

import { uuidSchema } from './primitives.js';

export const institutionSchema = z.object({
  id: uuidSchema,
  name: z.string().min(1)
});

export const institutionsResponseSchema = z.object({
  institutions: z.array(institutionSchema)
});

export const institutionWriteSchema = z
  .object({ name: z.string().trim().min(1).max(120) })
  .strict();

export type Institution = z.infer<typeof institutionSchema>;
export type InstitutionsResponse = z.infer<typeof institutionsResponseSchema>;
export type InstitutionWrite = z.infer<typeof institutionWriteSchema>;
