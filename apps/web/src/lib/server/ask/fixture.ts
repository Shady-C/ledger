import type { AskCompletionRequest, AskModelTier, AskProvider } from './provider.js';

function preset(question: string) {
  const absolute = question.match(/\b(\d{4}-\d{2}-\d{2})\b.*\b(\d{4}-\d{2}-\d{2})\b/);
  if (absolute?.[1] && absolute[2]) return { kind: 'absolute', from: absolute[1], to: absolute[2] } as const;
  const days = question.match(/\b(?:last|rolling)\s+(\d{1,3})\s+days?\b/i)?.[1];
  if (days && Number(days) >= 1 && Number(days) <= 366) return { kind: 'rolling_days', days: Number(days) } as const;
  if (/all history|all time/i.test(question)) return { kind: 'preset', value: 'all' } as const;
  if (/last quarter|previous quarter/i.test(question)) return { kind: 'preset', value: 'last_quarter' } as const;
  if (/this quarter/i.test(question)) return { kind: 'preset', value: 'this_quarter' } as const;
  if (/last year|previous year/i.test(question)) return { kind: 'preset', value: 'last_year' } as const;
  if (/year[ -]to[ -]date|this year|\bytd\b/i.test(question)) return { kind: 'preset', value: 'year_to_date' } as const;
  if (/this month/i.test(question)) return { kind: 'preset', value: 'this_month' } as const;
  if (/last month|previous month/i.test(question)) return { kind: 'preset', value: 'last_month' } as const;
  if (/24 months/i.test(question)) return { kind: 'preset', value: 'last_24_months' } as const;
  if (/12 months|last year/i.test(question)) return { kind: 'preset', value: 'last_12_months' } as const;
  if (/6 months/i.test(question)) return { kind: 'preset', value: 'last_6_months' } as const;
  if (/3 months/i.test(question)) return { kind: 'preset', value: 'last_3_months' } as const;
  return { kind: 'preset', value: 'last_12_months' } as const;
}

function market(question: string, fallback: 'ALL' | 'CA' | 'TZ') {
  if (/tanzania|\btz\b/i.test(question)) return 'TZ' as const;
  if (/canada|\bca\b/i.test(question)) return 'CA' as const;
  if (/all markets|all accounts/i.test(question)) return 'ALL' as const;
  return fallback;
}

function entity(question: string) {
  if (/\bby\s+(?:account|category|merchant)s?\b/iu.test(question)) return undefined;
  const patterns: Array<['account' | 'category' | 'merchant', RegExp]> = [
    ['category', /\b(?:category|on)\s+["']?([\p{L}][\p{L}\p{N} &.'-]{1,40})["']?/iu],
    ['merchant', /\b(?:merchant|at)\s+["']?([\p{L}][\p{L}\p{N} &.'-]{1,40})["']?/iu],
    ['account', /\baccount\s+["']?([\p{L}][\p{L}\p{N} &.'-]{1,40})["']?/iu]
  ];
  for (const [kind, pattern] of patterns) {
    const match = question.match(pattern);
    if (match?.[1]) return { kind, term: match[1].trim().replace(/\s+(?:last|this|over|for|vs).*$/i, '') };
  }
  return undefined;
}

export class FixtureAskProvider implements AskProvider {
  readonly providerName = 'fixture';

  modelName(tier: AskModelTier) {
    return `fixture-${tier}`;
  }

  async complete(request: AskCompletionRequest): Promise<unknown> {
    const payload = JSON.parse(request.messages.at(-1)?.content ?? '{}') as Record<string, unknown>;
    if (request.modelTier === 'cheap') {
      const facts = Array.isArray(payload.facts) ? payload.facts as Array<{ id?: unknown }> : [];
      return {
        blocks: [{
          segments: facts.slice(0, 6).map((fact) => ({ type: 'fact_ref', ref: String(fact.id) }))
        }]
      };
    }
    const question = String(payload.question ?? '');
    const activeMarket = ['ALL', 'CA', 'TZ'].includes(String(payload.activeMarket))
      ? String(payload.activeMarket) as 'ALL' | 'CA' | 'TZ'
      : 'ALL';
    const activeHomeCurrency = String(payload.activeHomeCurrency ?? '').toUpperCase();
    if (/\b(select|insert|update|delete|drop|alter)\b.*\b(from|into|table|where)\b|raw sql/i.test(question)) {
      return { version: 1, disposition: 'unsupported', reasonCode: 'raw_sql', message: 'Ask cannot run model-authored SQL.' };
    }
    if (/forecast|predict|next month|future spending/i.test(question)) {
      return { version: 1, disposition: 'unsupported', reasonCode: 'forecasting', message: 'Forecasting is outside Phase 3.' };
    }
    if (
      /\b(?:delete|update|create|dismiss|confirm|edit|rename|categorize|assign|mark|save)\b/i.test(question)
      || /\b(?:change|set)\s+(?:a|an|the|this|that|my|transaction|category|merchant|account|status|cadence|amount)\b/i.test(question)
    ) {
      return { version: 1, disposition: 'unsupported', reasonCode: 'write_request', message: 'Ask is read-only.' };
    }
    if (/should i|advice|recommend/i.test(question)) {
      return { version: 1, disposition: 'unsupported', reasonCode: 'financial_advice', message: 'Ask does not provide financial advice.' };
    }
    if (/net worth|balance|import status|reconciliation/i.test(question)) {
      return { version: 1, disposition: 'unsupported', reasonCode: 'unsupported_dataset', message: 'That dataset is outside the Phase 3 Ask catalog.' };
    }
    if (/\bbudget|\binvestment|\binvesting|\bportfolio/i.test(question)) {
      return { version: 1, disposition: 'unsupported', reasonCode: 'unsupported_dataset', message: 'That dataset is outside the Phase 3 Ask catalog.' };
    }
    // Preserve ordinary prose such as "spent in the last month". A reporting
    // currency override is recognized here only for an uppercase ISO-style
    // code; broader interpretation belongs to the live planner.
    const requestedCurrency = question.match(/\b(?:in|as|using)\s+([A-Z]{3})\b/)?.[1];
    if (requestedCurrency && requestedCurrency !== activeHomeCurrency) {
      return { version: 1, disposition: 'unsupported', reasonCode: 'unsupported_currency', message: 'Ask uses the active home currency and never switches reporting currency.' };
    }
    const common = { id: 'q1', market: market(question, activeMarket), date: preset(question), entity: entity(question) };
    const withoutUndefined = <T extends Record<string, unknown>>(value: T) =>
      Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined));
    if (/season|typically|usual month/i.test(question)) {
      return { version: 1, disposition: 'execute', queries: [withoutUndefined({ ...common, dataset: 'seasonality' })] };
    }
    if (/recurring|subscription|renewal|overdue/i.test(question)) {
      return { version: 1, disposition: 'execute', queries: [withoutUndefined({
        ...common,
        dataset: 'recurring',
        overdue: /overdue/i.test(question) || undefined,
        priceChanged: /price (?:change|increase)|changed price/i.test(question) || undefined,
        occurrenceLimit: 3,
        limit: 20
      })] };
    }
    if (/finding|unusual|anomal|duplicate|needs review/i.test(question)) {
      return { version: 1, disposition: 'execute', queries: [withoutUndefined({ ...common, dataset: 'findings', status: /new/i.test(question) ? 'new' : undefined, severity: /critical/i.test(question) ? 'critical' : undefined, mode: /how many|count/i.test(question) ? 'count' : 'list', limit: 20 })] };
    }
    if (/fx|foreign exchange|markup|fee/i.test(question)) {
      return { version: 1, disposition: 'execute', queries: [withoutUndefined({ ...common, dataset: 'fx', mode: /show|transaction|evidence/i.test(question) ? 'evidence' : 'summary', limit: 20 })] };
    }
    if (/transaction|purchase|charge|evidence|behind/i.test(question)) {
      if (/how many|transaction count|number of transactions|valued count|pending(?:-| )?fx count/i.test(question)) {
        const metric = /pending/i.test(question) ? 'pending_fx_count'
          : /valued/i.test(question) ? 'valued_count' : 'transaction_count';
        return { version: 1, disposition: 'execute', queries: [withoutUndefined({ ...common, dataset: 'aggregate', metrics: [metric], groupBy: 'total', comparison: 'none', limit: 20 })] };
      }
      return { version: 1, disposition: 'execute', queries: [withoutUndefined({ ...common, dataset: 'transactions', sort: 'date_desc', limit: 20 })] };
    }
    const groupBy = /categor/i.test(question) ? 'category'
      : /merchant/i.test(question) ? 'merchant'
        : /account/i.test(question) ? 'account'
          : /monthly|trend|over time/i.test(question) ? 'month' : 'total';
    return {
      version: 1,
      disposition: 'execute',
      queries: [withoutUndefined({
        ...common,
        dataset: 'aggregate',
        metrics: [/inflow|income/i.test(question) ? 'inflow' : /outflow/i.test(question) ? 'outflow' : /net cash/i.test(question) ? 'net_cashflow' : 'spending'],
        groupBy,
        comparison: /compare|versus|\bvs\b|change|drove/i.test(question) ? 'previous_period' : 'none',
        limit: 20
      })]
    };
  }
}
