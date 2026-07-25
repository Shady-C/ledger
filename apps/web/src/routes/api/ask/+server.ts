import { json } from '@sveltejs/kit';
import { askRequestSchema } from '@ledger/shared-types';

import { apiError, privateReadHeaders, validationError } from '$lib/server/api.js';
import {
  askLedger,
  AskAnalyticsRebuildingError,
  AskBusyError,
  AskDisabledError,
  AskInvalidEntitySelectionError,
  AskPlanningError,
  AskUnavailableError
} from '$lib/server/ask/service.js';
import {
  AskProviderResponseError,
  AskProviderTimeoutError,
  AskProviderUnavailableError
} from '$lib/server/ask/provider.js';

export async function POST({ request }) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_request', 'Expected a JSON Ask request.');
  }
  const parsed = askRequestSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);
  try {
    const response = await askLedger(parsed.data, { signal: request.signal });
    return json(response, { headers: privateReadHeaders });
  } catch (error) {
    if (error instanceof AskInvalidEntitySelectionError) {
      return apiError(400, 'invalid_request', error.message);
    }
    if (error instanceof AskBusyError) return apiError(429, 'ask_busy', error.message);
    if (error instanceof AskPlanningError || error instanceof AskProviderResponseError) {
      return apiError(502, 'ask_planning_failed', 'The question could not be converted into a safe query plan.');
    }
    if (error instanceof AskDisabledError) return apiError(503, 'ask_disabled', error.message);
    if (error instanceof AskUnavailableError || error instanceof AskProviderUnavailableError) {
      return apiError(503, 'ask_provider_unavailable', 'The configured Ask provider is unavailable.');
    }
    if (error instanceof AskAnalyticsRebuildingError) return apiError(503, 'analytics_rebuilding', error.message);
    if (
      error instanceof AskProviderTimeoutError
      || request.signal.aborted
      || (typeof error === 'object' && error !== null && 'code' in error && error.code === '57014')
    ) {
      return apiError(504, 'ask_timeout', 'The Ask request timed out.');
    }
    return apiError(500, 'internal_error', 'The Ask request could not be completed.');
  }
}
