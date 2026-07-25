import Anthropic from '@anthropic-ai/sdk';

import type { AskCompletionRequest, AskModelTier, AskProvider } from './provider.js';
import {
  AskProviderResponseError,
  AskProviderTimeoutError,
  AskProviderUnavailableError
} from './provider.js';

type AnthropicAskProviderOptions = {
  apiKey: string;
  capableModel: string;
  cheapModel: string;
  timeoutMs: number;
};

export class AnthropicAskProvider implements AskProvider {
  readonly providerName = 'anthropic';
  private readonly client: Anthropic;
  private readonly models: Record<AskModelTier, string>;
  private readonly timeoutMs: number;

  constructor(options: AnthropicAskProviderOptions) {
    this.client = new Anthropic({ apiKey: options.apiKey, maxRetries: 0, timeout: options.timeoutMs });
    this.models = { capable: options.capableModel, cheap: options.cheapModel };
    this.timeoutMs = options.timeoutMs;
  }

  modelName(tier: AskModelTier) {
    return this.models[tier];
  }

  async complete(request: AskCompletionRequest): Promise<unknown> {
    try {
      const response = await this.client.messages.create(
        {
          model: this.models[request.modelTier],
          max_tokens: 4096,
          system: request.system,
          messages: request.messages,
          output_config: {
            format: { type: 'json_schema', schema: request.schema }
          }
        },
        { signal: request.signal, timeout: this.timeoutMs, maxRetries: 0 }
      );
      if (response.stop_reason === 'refusal') {
        throw new AskProviderResponseError('The Ask provider refused the structured request.');
      }
      if (response.stop_reason === 'max_tokens' || response.stop_reason === 'model_context_window_exceeded') {
        throw new AskProviderResponseError('The Ask provider response was truncated.');
      }
      const text = response.content
        .filter((block) => block.type === 'text')
        .map((block) => block.text)
        .join('');
      try {
        return JSON.parse(text) as unknown;
      } catch (error) {
        throw new AskProviderResponseError('The Ask provider returned invalid JSON.');
      }
    } catch (error) {
      if (
        error instanceof AskProviderResponseError
        || error instanceof AskProviderTimeoutError
        || error instanceof AskProviderUnavailableError
      ) {
        throw error;
      }
      if (request.signal?.aborted || error instanceof Anthropic.APIConnectionTimeoutError) {
        throw new AskProviderTimeoutError();
      }
      throw new AskProviderUnavailableError(error instanceof Error ? error.message : undefined);
    }
  }
}
