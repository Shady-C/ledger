import { afterEach, describe, expect, it, vi } from 'vitest';

import { POST as postAsk } from '../../../routes/api/ask/+server.js';
import { GET as getAskStatus } from '../../../routes/api/ask/status/+server.js';

afterEach(() => vi.unstubAllEnvs());

function request(body: string) {
  return new Request('http://ledger.test/api/ask', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body
  });
}

describe('Ask HTTP boundary', () => {
  it('keeps status secret-free, no-store, and independently disabled by default', async () => {
    vi.stubEnv('ASK_ENABLED', 'false');
    vi.stubEnv('ASK_PROVIDER_MODE', 'live');
    vi.stubEnv('ANTHROPIC_API_KEY', 'do-not-return-this');
    const response = getAskStatus();
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(await response.json()).toEqual({ enabled: false, available: false, reason: 'disabled' });
  });

  it('reports invalid provider configuration without exposing its value', async () => {
    vi.stubEnv('ASK_ENABLED', 'true');
    vi.stubEnv('ASK_PROVIDER_MODE', 'unexpected-secret-mode');
    const response = getAskStatus();
    expect(await response.json()).toEqual({
      enabled: true,
      available: false,
      reason: 'invalid_configuration'
    });
  });

  it('rejects malformed JSON and invalid IANA timezones as invalid_request', async () => {
    const malformed = await postAsk({ request: request('{') } as Parameters<typeof postAsk>[0]);
    expect(malformed.status).toBe(400);
    expect(await malformed.json()).toMatchObject({ error: { code: 'invalid_request' } });

    const invalidZone = await postAsk({
      request: request(JSON.stringify({
        question: 'How much did I spend?',
        market: 'ALL',
        timeZone: 'Not/A_TimeZone',
        history: []
      }))
    } as Parameters<typeof postAsk>[0]);
    expect(invalidZone.status).toBe(400);
    expect(await invalidZone.json()).toMatchObject({ error: { code: 'invalid_request' } });
  });

  it('returns the stable disabled and unavailable operational errors before any ledger read', async () => {
    vi.stubEnv('ASK_ENABLED', 'false');
    const disabled = await postAsk({
      request: request(JSON.stringify({
        question: 'How much did I spend?',
        market: 'ALL',
        timeZone: 'UTC',
        history: []
      }))
    } as Parameters<typeof postAsk>[0]);
    expect(disabled.status).toBe(503);
    expect(await disabled.json()).toMatchObject({ error: { code: 'ask_disabled' } });

    vi.stubEnv('ASK_ENABLED', 'true');
    vi.stubEnv('ASK_PROVIDER_MODE', 'live');
    vi.stubEnv('ANTHROPIC_API_KEY', '');
    const unavailable = await postAsk({
      request: request(JSON.stringify({
        question: 'How much did I spend?',
        market: 'ALL',
        timeZone: 'UTC',
        history: []
      }))
    } as Parameters<typeof postAsk>[0]);
    expect(unavailable.status).toBe(503);
    expect(await unavailable.json()).toMatchObject({ error: { code: 'ask_provider_unavailable' } });
  });
});
