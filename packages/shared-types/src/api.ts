import { z } from 'zod';

export const apiErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.record(z.array(z.string())).optional()
  })
});

export type ApiError = z.infer<typeof apiErrorSchema>;
