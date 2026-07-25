import { randomUUID } from 'node:crypto';

import {
  askAnswerBlockSchema,
  askPlanV1Schema,
  askResponseSchema,
  type AskAnswerBlock,
  type AskLocalClarificationReference,
  type AskMarket,
  type AskPlanV1,
  type AskRequest,
  type AskResponse
} from '@ledger/shared-types';
import type { Pool, PoolClient } from 'pg';
import { z } from 'zod';

import { getPool } from '../db.js';
import { askConfig } from '../env.js';
import { AnthropicAskProvider } from './anthropic.js';
import {
  AskAnalyticsRebuildingError,
  AskInvalidEntitySelectionError,
  executeAskPlan,
  readAskAnalyticsContext,
  type AskExecutionResult,
  type AskFact
} from './executor.js';
import { FixtureAskProvider } from './fixture.js';
import {
  askNarratorJsonSchema,
  askPlannerJsonSchema,
  narratorSystemPrompt,
  plannerMessage,
  plannerSystemPrompt
} from './prompts.js';
import type { AskProvider } from './provider.js';
import {
  AskProviderResponseError,
  AskProviderTimeoutError,
  AskProviderUnavailableError,
  type AskCompletionRequest
} from './provider.js';
import { dateInTimeZone, validatedTimeZone } from './time.js';

export class AskDisabledError extends Error {
  constructor() { super('Ask is not enabled.'); this.name = 'AskDisabledError'; }
}

export class AskUnavailableError extends Error {
  constructor() { super('Ask provider configuration is incomplete.'); this.name = 'AskUnavailableError'; }
}

export class AskBusyError extends Error {
  constructor() { super('Ask is already handling the maximum number of requests.'); this.name = 'AskBusyError'; }
}

export class AskPlanningError extends Error {
  constructor() { super('The question could not be converted into a safe query plan.'); this.name = 'AskPlanningError'; }
}

const narratorOutputSchema = z.object({
  blocks: z.array(z.object({
    heading: z.string().min(1).max(120).optional(),
    segments: z.array(z.union([
      z.object({ type: z.literal('text'), text: z.string().min(1).max(300) }).strict(),
      z.object({ type: z.literal('fact_ref'), ref: z.string().regex(/^f\d+$/) }).strict()
    ])).min(1).max(20)
  }).strict()).min(1).max(8)
}).strict();

const safeConnectiveText = new Set([
  'Here is what the ledger shows: ',
  'Supporting evidence: ',
  'In comparison, ',
  'Also, ',
  'Coverage note: ',
  ' '
]);
const safeNarratorHeadings = new Set(['Answer', 'Summary', 'Comparison', 'Evidence', 'Coverage']);

let activeRequests = 0;
const MAX_CONCURRENT_ASKS = 2;
const ASK_REQUEST_BUDGET_MS = 45_000;

export function acquireAskSlot() {
  if (activeRequests >= MAX_CONCURRENT_ASKS) throw new AskBusyError();
  activeRequests += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    activeRequests -= 1;
  };
}

function providerFromConfig(): AskProvider {
  const config = askConfig();
  if (config.providerMode === 'stub') return new FixtureAskProvider();
  return new AnthropicAskProvider({
    apiKey: config.apiKey,
    capableModel: config.capableModel,
    cheapModel: config.cheapModel,
    timeoutMs: config.timeoutMs
  });
}

function linkedSignal(parent: AbortSignal | undefined, timeoutMs: number) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(new Error('Ask request timed out')), timeoutMs);
  const abort = () => controller.abort(parent?.reason);
  if (parent?.aborted) abort();
  else parent?.addEventListener('abort', abort, { once: true });
  return {
    signal: controller.signal,
    dispose() {
      clearTimeout(timeout);
      parent?.removeEventListener('abort', abort);
    }
  };
}

function throwIfAborted(signal: AbortSignal) {
  if (signal.aborted) throw new AskProviderTimeoutError();
}

function connectWithSignal(pool: Pool, signal: AbortSignal): Promise<PoolClient> {
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    let settled = false;
    const abort = () => {
      if (settled) return;
      settled = true;
      reject(new AskProviderTimeoutError());
    };
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
    void pool.connect().then((client) => {
      signal.removeEventListener('abort', abort);
      if (settled) {
        client.release();
        return;
      }
      settled = true;
      resolve(client);
    }, (error: unknown) => {
      signal.removeEventListener('abort', abort);
      if (settled) return;
      settled = true;
      reject(error);
    });
  });
}

function signalGuardedClient(client: PoolClient, signal: AbortSignal): PoolClient {
  const rawQuery = client.query.bind(client) as unknown as (...args: unknown[]) => unknown;
  const guardedQuery = (...args: unknown[]) => {
    throwIfAborted(signal);
    return rawQuery(...args);
  };
  return new Proxy(client, {
    get(target, property, receiver) {
      return property === 'query' ? guardedQuery : Reflect.get(target, property, receiver);
    }
  });
}

async function readOnlySnapshot<T>(
  pool: Pool,
  signal: AbortSignal,
  operation: (client: PoolClient) => Promise<T>
) {
  const client = await connectWithSignal(pool, signal);
  let backendPid: number | undefined;
  const cancel = () => {
    if (backendPid === undefined) return;
    void pool.query('SELECT pg_cancel_backend($1)', [backendPid]).catch(() => undefined);
  };
  try {
    throwIfAborted(signal);
    await client.query('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY');
    await client.query("SET LOCAL statement_timeout = '10s'");
    const backend = await client.query<{ pid: number }>('SELECT pg_backend_pid()::int AS pid');
    backendPid = backend.rows[0]?.pid;
    signal.addEventListener('abort', cancel, { once: true });
    if (signal.aborted) {
      cancel();
      throwIfAborted(signal);
    }
    const guarded = signalGuardedClient(client, signal);
    const result = await operation(guarded);
    await guarded.query('COMMIT');
    throwIfAborted(signal);
    return result;
  } catch (error) {
    await client.query('ROLLBACK').catch(() => undefined);
    throw error;
  } finally {
    signal.removeEventListener('abort', cancel);
    // Do not return an aborted backend to the pool while its asynchronous
    // cancel request may still be in flight.
    client.release(signal.aborted);
  }
}

async function readiness(
  pool: Pool,
  request: AskRequest,
  asOfDate: string,
  timeZone: string,
  signal: AbortSignal
) {
  return readOnlySnapshot(
    pool,
    signal,
    (client) => readAskAnalyticsContext(client, request.market, asOfDate, timeZone)
  );
}

async function executeInSnapshot(
  pool: Pool,
  request: AskRequest,
  plan: Extract<AskPlanV1, { disposition: 'execute' }>,
  asOfDate: string,
  timeZone: string,
  expected: { baseCurrency: string; analyticsGeneration: number },
  signal: AbortSignal,
  localSelection?: AskLocalClarificationReference
) {
  return readOnlySnapshot(pool, signal, async (client) => {
    const context = await readAskAnalyticsContext(client, request.market, asOfDate, timeZone);
    if (
      context.baseCurrency !== expected.baseCurrency
      || context.analyticsGeneration !== expected.analyticsGeneration
      || context.sourceChangedSinceGeneration
    ) {
      throw new AskAnalyticsRebuildingError();
    }
    return executeAskPlan(client, plan, context, localSelection);
  });
}

export function deterministicAnswer(facts: AskFact[]): AskAnswerBlock[] {
  const selected = facts.slice(0, 12);
  return selected.length > 0
    ? [{ heading: 'Answer', segments: selected.map((fact) => ({ type: 'fact' as const, ref: fact.id, text: fact.text })) }]
    : [];
}

export function groundedNarration(value: unknown, facts: AskFact[]): AskAnswerBlock[] | null {
  const parsed = narratorOutputSchema.safeParse(value);
  if (!parsed.success) return null;
  const byId = new Map(facts.map((fact) => [fact.id, fact]));
  const blocks: AskAnswerBlock[] = [];
  for (const block of parsed.data.blocks) {
    if (block.heading && !safeNarratorHeadings.has(block.heading)) return null;
    const segments: AskAnswerBlock['segments'] = [];
    for (const segment of block.segments) {
      if (segment.type === 'text') {
        if (!safeConnectiveText.has(segment.text)) return null;
        segments.push({ type: 'text', text: segment.text });
      } else {
        const fact = byId.get(segment.ref);
        if (!fact) return null;
        segments.push({ type: 'fact', ref: fact.id, text: fact.text });
      }
    }
    if (segments.length > 0) blocks.push({ ...(block.heading ? { heading: block.heading } : {}), segments });
  }
  const validated = z.array(askAnswerBlockSchema).min(1).max(8).safeParse(blocks);
  return validated.success ? validated.data : null;
}

async function timedCompletion(
  provider: AskProvider,
  requestId: string,
  queryCount: number,
  request: AskCompletionRequest,
  timeoutMs: number
) {
  const started = Date.now();
  const deadline = linkedSignal(request.signal, timeoutMs);
  let callError: string | null = null;
  try {
    throwIfAborted(deadline.signal);
    return await new Promise<unknown>((resolve, reject) => {
      let settled = false;
      const finish = (callback: (value: unknown) => void, value: unknown) => {
        if (settled) return;
        settled = true;
        deadline.signal.removeEventListener('abort', abort);
        callback(value);
      };
      const abort = () => finish(reject, new AskProviderTimeoutError());
      deadline.signal.addEventListener('abort', abort, { once: true });
      if (deadline.signal.aborted) {
        abort();
        return;
      }
      void provider.complete({ ...request, signal: deadline.signal }).then(
        (value) => finish(resolve, value),
        (error: unknown) => finish(reject, error)
      );
    });
  } catch (error) {
    callError = errorCode(error);
    throw error;
  } finally {
    deadline.dispose();
    console.info('[ask] provider call', {
      requestId,
      disposition: 'provider_call',
      modelTier: request.modelTier,
      durationMs: Date.now() - started,
      queryCount,
      errorCode: callError
    });
  }
}

export async function narrate(
  provider: AskProvider,
  execution: AskExecutionResult,
  signal: AbortSignal,
  requestId: string,
  timeoutMs: number
) {
  const safeFacts = execution.facts.map((fact) => ({ id: fact.id, role: fact.role, dataset: fact.dataset }));
  try {
    const output = await timedCompletion(provider, requestId, execution.evidence.length, {
      system: narratorSystemPrompt,
      messages: [{ role: 'user', content: JSON.stringify({ facts: safeFacts }) }],
      schema: askNarratorJsonSchema,
      modelTier: 'cheap',
      signal
    }, timeoutMs);
    return groundedNarration(output, execution.facts) ?? deterministicAnswer(execution.facts);
  } catch {
    // Provider-specific narration failures degrade to deterministic local
    // prose. Cancellation of the enclosing browser/request budget does not.
    if (signal.aborted) throw new AskProviderTimeoutError();
    return deterministicAnswer(execution.facts);
  }
}

function errorCode(error: unknown) {
  if (error instanceof AskInvalidEntitySelectionError) return 'invalid_request';
  if (error instanceof AskBusyError) return 'ask_busy';
  if (error instanceof AskPlanningError || error instanceof AskProviderResponseError) return 'ask_planning_failed';
  if (error instanceof AskDisabledError) return 'ask_disabled';
  if (error instanceof AskUnavailableError || error instanceof AskProviderUnavailableError) return 'ask_provider_unavailable';
  if (error instanceof AskAnalyticsRebuildingError) return 'analytics_rebuilding';
  if (error instanceof AskProviderTimeoutError) return 'ask_timeout';
  return 'internal_error';
}

function validatedResponse(value: AskResponse) {
  const parsed = askResponseSchema.safeParse(value);
  if (!parsed.success) throw new Error('Ask constructed an invalid response.');
  return parsed.data;
}

export function normalizePlanMarkets(plan: AskPlanV1, activeMarket: AskMarket): AskPlanV1 {
  if (plan.disposition !== 'execute') return plan;
  return {
    ...plan,
    queries: plan.queries.map((query) => ({
      ...query,
      market: query.market ?? activeMarket
    }))
  };
}

type CodeOwnedUnsupported = Pick<
  Extract<AskPlanV1, { disposition: 'unsupported' }>,
  'reasonCode' | 'message'
> & { suggestions: string[] };

function codeOwnedUnsupportedIntent(question: string): CodeOwnedUnsupported | null {
  const normalized = question.normalize('NFKC');
  const rawSql = /\braw\s+sql\b|\b(?:run|execute|write)\s+(?:a\s+)?sql\b|\bselect\s+\*\s+from\b|\bselect\b[\s\S]*\bfrom\s+(?:txn|account|statement|category|merchant|fx_rate|analytics_\w+)\b|\binsert\s+into\b|\bdelete\s+from\b|\bupdate\s+["\w.]+\s+set\b|\b(?:drop|alter|truncate|create)\s+table\b/iu;
  if (rawSql.test(normalized)) {
    return {
      reasonCode: 'raw_sql',
      message: 'Ask cannot run model-authored SQL.',
      suggestions: ['Ask about spending, cash flow, or supporting transactions instead.']
    };
  }

  const writeRequest = /\b(?:delete|remove|erase|edit|rename|categorize|assign|dismiss|confirm|save)\s+(?:a\s+|an\s+|the\s+|this\s+|that\s+|my\s+|latest\s+)?(?:transactions?|accounts?|categories|merchants?|findings?|recurring\s+series)\b|\b(?:create|add)\s+(?:a\s+|an\s+|the\s+|my\s+)?(?:transaction|account|category|merchant|finding|budget)\b|\b(?:change|set|mark|update)\s+(?:a\s+|an\s+|the\s+|this\s+|that\s+|my\s+)?(?:transaction|account|category|merchant|finding|status|cadence|amount)\b/iu;
  if (writeRequest.test(normalized)) {
    return {
      reasonCode: 'write_request',
      message: 'Ask is read-only and cannot change ledger data.',
      suggestions: ['Ask to inspect the related transactions or findings instead.']
    };
  }

  const forecasting = /\b(?:forecast|forecasting|predict|prediction|projection)\b|\b(?:what|how much)\s+(?:will|would)\b[\s\S]*\b(?:spend|spending|income|cash\s*flow)\b/iu;
  if (forecasting.test(normalized)) {
    return {
      reasonCode: 'forecasting',
      message: 'Forecasting is outside Phase 3 Ask.',
      suggestions: ['Ask about historical spending trends or seasonality instead.']
    };
  }

  const financialAdvice = /\bshould\s+i\b|\b(?:can|could)\s+i\s+afford\b|\bwould\s+you\s+recommend\b|\b(?:financial\s+)?advice\b|\brecommend(?:ation|ations)?\b|\bis\s+it\s+(?:wise|better)\b/iu;
  if (financialAdvice.test(normalized)) {
    return {
      reasonCode: 'financial_advice',
      message: 'Ask does not provide financial advice.',
      suggestions: ['Ask for deterministic spending or cash-flow evidence instead.']
    };
  }

  const balanceOrNetWorth = /\bnet[\s-]*worth\b|\b(?:account|bank|card|cash|current|available|opening|closing)\s+balances?\b|\bbalances?\s+(?:for|of|on|in|across)\s+(?:my\s+)?(?:accounts?|banks?|cards?)\b|\b(?:what(?:'s|\s+is)|show|list|give\s+me)\s+(?:me\s+)?(?:my\s+)?(?:current\s+)?balances?\b/iu;
  if (balanceOrNetWorth.test(normalized)) {
    return {
      reasonCode: 'unsupported_dataset',
      message: 'Balances and net worth are outside Phase 3 Ask.',
      suggestions: ['Ask about inflow, outflow, spending, or net cash flow instead.']
    };
  }

  return null;
}

export async function askLedger(
  request: AskRequest,
  options: { signal?: AbortSignal; provider?: AskProvider; now?: Date; pool?: Pool } = {}
): Promise<AskResponse> {
  const config = askConfig();
  if (!config.enabled) throw new AskDisabledError();
  if (!config.available) throw new AskUnavailableError();
  const releaseSlot = acquireAskSlot();
  const deadline = linkedSignal(options.signal, ASK_REQUEST_BUDGET_MS);
  const requestId = randomUUID();
  const started = Date.now();
  try {
    const unsupported = codeOwnedUnsupportedIntent(request.question);
    if (unsupported) {
      console.info('[ask] completed', { requestId, disposition: 'unsupported', queryCount: 0, durationMs: Date.now() - started });
      return validatedResponse({ kind: 'unsupported', requestId, ...unsupported });
    }
    const timeZone = validatedTimeZone(request.timeZone);
    const asOfDate = dateInTimeZone(options.now ?? new Date(), timeZone);
    const pool = options.pool ?? getPool();
    const initialContext = await readiness(pool, request, asOfDate, timeZone, deadline.signal);
    if (initialContext.sourceChangedSinceGeneration) throw new AskAnalyticsRebuildingError();
    const provider = options.provider ?? providerFromConfig();
    let plan: AskPlanV1;
    if (request.localSelection) {
      plan = normalizePlanMarkets(request.localSelection.plan, request.market);
    } else {
      let rawPlan: unknown;
      try {
        rawPlan = await timedCompletion(provider, requestId, 0, {
          system: plannerSystemPrompt,
          messages: [{ role: 'user', content: plannerMessage(request, asOfDate, timeZone, initialContext.baseCurrency) }],
          schema: askPlannerJsonSchema,
          modelTier: 'capable',
          signal: deadline.signal
        }, config.timeoutMs);
      } catch (error) {
        if (error instanceof AskProviderResponseError) throw new AskPlanningError();
        throw error;
      }
      const parsedPlan = askPlanV1Schema.safeParse(rawPlan);
      if (!parsedPlan.success) throw new AskPlanningError();
      plan = normalizePlanMarkets(parsedPlan.data, request.market);
    }
    if (plan.disposition === 'clarify') {
      console.info('[ask] completed', { requestId, disposition: 'clarification_required', queryCount: 0, durationMs: Date.now() - started });
      return validatedResponse({ kind: 'clarification_required', requestId, prompt: plan.prompt, choices: plan.choices ?? [], plan });
    }
    if (plan.disposition === 'unsupported') {
      console.info('[ask] completed', { requestId, disposition: 'unsupported', queryCount: 0, durationMs: Date.now() - started });
      return validatedResponse({ kind: 'unsupported', requestId, reasonCode: plan.reasonCode, message: plan.message, suggestions: plan.suggestions ?? [] });
    }
    const execution = await executeInSnapshot(
      pool,
      request,
      plan,
      asOfDate,
      timeZone,
      initialContext,
      deadline.signal,
      request.localSelection
    );
    if ('prompt' in execution) {
      console.info('[ask] completed', { requestId, disposition: 'clarification_required', queryCount: 0, durationMs: Date.now() - started });
      return validatedResponse({ kind: 'clarification_required', requestId, prompt: execution.prompt, choices: execution.choices, plan: execution.plan });
    }
    if (execution.facts.length === 0 && execution.evidence.every((item) => item.rows.length === 0)) {
      console.info('[ask] completed', { requestId, disposition: 'no_data', queryCount: plan.queries.length, durationMs: Date.now() - started });
      return validatedResponse({ kind: 'no_data', requestId, plan, message: 'No ledger data matched the resolved question.', context: execution.context });
    }
    const answer = await narrate(
      provider,
      execution,
      deadline.signal,
      requestId,
      config.timeoutMs
    );
    throwIfAborted(deadline.signal);
    if (answer.length === 0) throw new AskProviderResponseError('No grounded answer could be rendered.');
    console.info('[ask] completed', { requestId, disposition: 'answered', queryCount: plan.queries.length, durationMs: Date.now() - started });
    return validatedResponse({ kind: 'answered', requestId, plan, answer, evidence: execution.evidence, context: execution.context, warnings: execution.warnings });
  } catch (error) {
    console.error('[ask] failed', {
      requestId,
      disposition: 'error',
      modelTier: null,
      durationMs: Date.now() - started,
      queryCount: 0,
      errorCode: errorCode(error)
    });
    throw error;
  } finally {
    deadline.dispose();
    releaseSlot();
  }
}

export { AskAnalyticsRebuildingError, AskInvalidEntitySelectionError };
