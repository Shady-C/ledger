import { describe, expect, it, vi } from 'vitest';

import { AnthropicAskProvider } from './anthropic.js';
import {
  AskProviderResponseError,
  AskProviderTimeoutError,
  AskProviderUnavailableError,
  type AskCompletionRequest
} from './provider.js';

function providerWithCreate(create: ReturnType<typeof vi.fn>) {
  const provider = new AnthropicAskProvider({
    apiKey: 'test-only-key',
    capableModel: 'capable-test-model',
    cheapModel: 'cheap-test-model',
    timeoutMs: 20_000
  });
  Object.defineProperty(provider, 'client', { value: { messages: { create } } });
  return provider;
}

const request: AskCompletionRequest = {
  system: 'closed test system',
  messages: [{ role: 'user', content: '{"question":"opaque test"}' }],
  schema: { type: 'object', additionalProperties: false },
  modelTier: 'capable'
};

describe('AnthropicAskProvider', () => {
  it('uses structured output, the selected tier, a 20-second bound, and no retries', async () => {
    const create = vi.fn().mockResolvedValue({
      stop_reason: 'end_turn',
      content: [{ type: 'text', text: '{"version":1}' }]
    });
    const provider = providerWithCreate(create);
    await expect(provider.complete(request)).resolves.toEqual({ version: 1 });
    expect(create).toHaveBeenCalledWith(expect.objectContaining({
      model: 'capable-test-model',
      system: request.system,
      messages: request.messages,
      output_config: { format: { type: 'json_schema', schema: request.schema } }
    }), expect.objectContaining({ timeout: 20_000, maxRetries: 0 }));
  });

  it.each(['refusal', 'max_tokens', 'model_context_window_exceeded'])(
    'rejects %s provider termination without retrying',
    async (stopReason) => {
      const provider = providerWithCreate(vi.fn().mockResolvedValue({
        stop_reason: stopReason,
        content: []
      }));
      await expect(provider.complete(request)).rejects.toBeInstanceOf(AskProviderResponseError);
    }
  );

  it('rejects malformed structured output', async () => {
    const provider = providerWithCreate(vi.fn().mockResolvedValue({
      stop_reason: 'end_turn',
      content: [{ type: 'text', text: 'not json' }]
    }));
    await expect(provider.complete(request)).rejects.toBeInstanceOf(AskProviderResponseError);
  });

  it('maps aborts to timeout and other transport failures to unavailable', async () => {
    const controller = new AbortController();
    controller.abort();
    const timedOut = providerWithCreate(vi.fn().mockRejectedValue(new Error('hidden transport detail')));
    await expect(timedOut.complete({ ...request, signal: controller.signal }))
      .rejects.toBeInstanceOf(AskProviderTimeoutError);

    const unavailable = providerWithCreate(vi.fn().mockRejectedValue(new Error('hidden transport detail')));
    await expect(unavailable.complete(request)).rejects.toBeInstanceOf(AskProviderUnavailableError);
  });
});
