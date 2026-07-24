import { json } from '@sveltejs/kit';
import type { ZodError } from 'zod';

import { ConfigurationError } from './env.js';

export function apiError(
  status: number,
  code: string,
  message: string,
  details?: Record<string, string[]>
) {
  return json(
    {
      error: {
        code,
        message,
        ...(details ? { details } : {})
      }
    },
    {
      status,
      headers: { 'cache-control': 'no-store' }
    }
  );
}

export function validationError(error: ZodError) {
  const details = Object.fromEntries(
    Object.entries(error.flatten().fieldErrors).filter(
      (entry): entry is [string, string[]] => Array.isArray(entry[1])
    )
  );
  return apiError(400, 'invalid_request', 'Some request values are invalid.', details);
}

export function unavailableOrInternal(error: unknown, context: string) {
  if (error instanceof ConfigurationError) {
    console.error(`[${context}] service configuration is incomplete: ${error.message}`);
    return apiError(503, 'service_unavailable', 'This service is not configured yet.');
  }
  console.error(`[${context}] request failed`, error);
  return apiError(500, 'internal_error', 'The request could not be completed.');
}

export const privateReadHeaders = {
  'cache-control': 'no-store',
  vary: 'accept-encoding'
};
