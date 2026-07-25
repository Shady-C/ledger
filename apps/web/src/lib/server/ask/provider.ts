export type AskModelTier = 'cheap' | 'capable';

export type AskProviderMessage = {
  role: 'user' | 'assistant';
  content: string;
};

export type AskCompletionRequest = {
  system: string;
  messages: AskProviderMessage[];
  schema: Record<string, unknown>;
  modelTier: AskModelTier;
  signal?: AbortSignal;
};

export interface AskProvider {
  readonly providerName: string;
  modelName(tier: AskModelTier): string;
  complete(request: AskCompletionRequest): Promise<unknown>;
}

export class AskProviderUnavailableError extends Error {
  constructor(message = 'The configured Ask provider is unavailable.') {
    super(message);
    this.name = 'AskProviderUnavailableError';
  }
}

export class AskProviderResponseError extends Error {
  constructor(message = 'The Ask provider returned an invalid response.') {
    super(message);
    this.name = 'AskProviderResponseError';
  }
}

export class AskProviderTimeoutError extends Error {
  constructor() {
    super('The Ask provider timed out.');
    this.name = 'AskProviderTimeoutError';
  }
}
