/** @vitest-environment jsdom */

import { cleanup, render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  AskExecutePlanV1,
  AskPlanV1,
  AskResponse,
  AskResponseContext
} from '@ledger/shared-types';

import AskPanel from './AskPanel.svelte';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const executePlan: AskExecutePlanV1 = {
  version: 1,
  disposition: 'execute',
  queries: [{
    id: 'q1',
    dataset: 'aggregate',
    date: { kind: 'preset', value: 'last_month' },
    metrics: ['spending'],
    groupBy: 'category',
    comparison: 'none',
    limit: 20
  }]
};

const context: AskResponseContext = {
  market: 'ALL',
  baseCurrency: 'CAD',
  asOfDate: '2026-07-25',
  timeZone: 'UTC',
  analyticsGeneration: 7,
  thresholdPolicyVersion: 'phase-2-v1',
  sourceWatermark: '2026-07-24T18:00:00.000Z',
  sourceChangedSinceGeneration: true,
  resolvedQueries: [{
    queryId: 'q1',
    dataset: 'aggregate',
    market: 'ALL',
    from: '2026-06-01',
    to: '2026-06-30'
  }],
  coverage: {
    status: 'partial',
    valuedTransactionCount: 18,
    pendingFxCount: 1,
    pendingByCurrency: [{ currency: 'USD', transactionCount: 1 }]
  }
};

const answeredResponse: AskResponse = {
  kind: 'answered',
  requestId: '11111111-1111-4111-8111-111111111111',
  plan: executePlan,
  answer: [{
    heading: 'Last month',
    segments: [
      { type: 'text', text: 'Dining led spending at ' },
      { type: 'fact', ref: 'f1', text: 'CAD 1,250.25' },
      { type: 'text', text: '.' }
    ]
  }],
  evidence: [
    {
      id: 'category-spending',
      queryId: 'q1',
      title: 'Category spending',
      kind: 'bar',
      columns: [
        { key: 'category', label: 'Category', type: 'text' },
        { key: 'spending', label: 'Spending', type: 'money', currency: 'CAD' }
      ],
      rows: [
        { category: 'Dining', spending: '1250.25' },
        { category: 'Transport', spending: '500.00' }
      ],
      coverage: context.coverage,
      truncated: false,
      drilldownPath: '/transactions?categoryId=33333333-3333-4333-8333-333333333333'
    },
    {
      id: 'spending-total',
      queryId: 'q1',
      title: 'Spending total',
      kind: 'metric',
      columns: [{ key: 'spending', label: 'Spending', type: 'money', currency: 'CAD' }],
      rows: [{ spending: '1750.25' }],
      coverage: context.coverage,
      truncated: false
    }
  ],
  context,
  warnings: ['The current valuation coverage is incomplete.']
};

function json(value: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' }
  }));
}

describe('AskPanel', () => {
  it('loads status independently and explains disabled Ask without exposing a question form', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) => json({ enabled: false, available: false, reason: 'disabled' }));
    vi.stubGlobal('fetch', fetchMock);

    render(AskPanel, { props: { market: 'CA', currency: 'CAD' } });

    expect(await screen.findByText('Ask is off')).toBeTruthy();
    expect(screen.getByText(/Ask is turned off/)).toBeTruthy();
    expect(screen.getByText('External AI disclosure')).toBeTruthy();
    expect(screen.queryByRole('textbox', { name: 'Question' })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/ask/status');
  });

  it('submits an exact scoped request and renders narration, evidence, warnings, charts, and query inspection', async () => {
    const requests: Record<string, unknown>[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/ask/status') {
        return json({ enabled: true, available: true, reason: null });
      }
      requests.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return json(answeredResponse);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(AskPanel, { props: { market: 'ALL', currency: 'CAD' } });
    await screen.findByRole('textbox', { name: 'Question' });
    await user.click(screen.getByRole('button', { name: 'How much did I spend last month?' }));
    await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));

    expect(await screen.findByRole('heading', { name: 'Answer' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Last month' })).toBeTruthy();
    expect(screen.getByText('Dining led spending at CAD 1,250.25.')).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Category spending bar chart' })).toBeTruthy();
    expect(screen.getAllByText('CAD 1,250.25').length).toBeGreaterThan(0);
    expect(screen.getByText(/1 transaction await CAD valuation/)).toBeTruthy();
    expect(screen.getByText(/Newer ledger activity exists/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open supporting records' }).getAttribute('href')).toContain('/transactions');

    await user.click(screen.getByText('Inspect normalized queries'));
    expect(screen.getByText(/"dataset": "aggregate"/)).toBeTruthy();
    expect(screen.getByText('Analytics generation').parentElement?.textContent).toContain('7');
    expect(screen.getByText('Resolved query ranges')).toBeTruthy();
    expect(screen.getByText('2026-06-01')).toBeTruthy();
    expect(screen.getByText('2026-06-30')).toBeTruthy();

    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({
      question: 'How much did I spend last month?',
      market: 'ALL',
      history: []
    });
    expect(typeof requests[0]?.timeZone).toBe('string');
    expect(Object.keys(requests[0]!).sort()).toEqual(['history', 'market', 'question', 'timeZone']);
  });

  it('plots negative financial values below the zero baseline', async () => {
    const signedResponse = structuredClone(answeredResponse);
    if (signedResponse.kind === 'answered') {
      signedResponse.evidence = [{
        id: 'monthly-net-cashflow',
        queryId: 'q1',
        title: 'Monthly net cash flow',
        kind: 'line',
        columns: [
          { key: 'month', label: 'Month', type: 'date' },
          { key: 'netCashflow', label: 'Net cash flow', type: 'money', currency: 'CAD' }
        ],
        rows: [
          { month: '2026-05-01', netCashflow: '100.00' },
          { month: '2026-06-01', netCashflow: '-100.00' }
        ],
        coverage: context.coverage,
        truncated: false
      }];
    }
    const fetchMock = vi.fn((input: RequestInfo | URL) => String(input) === '/api/ask/status'
      ? json({ enabled: true, available: true, reason: null })
      : json(signedResponse));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(AskPanel);
    const textbox = await screen.findByRole('textbox', { name: 'Question' });
    await user.type(textbox, 'Show monthly net cash flow');
    await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));

    const chart = await screen.findByRole('img', { name: 'Monthly net cash flow line chart' });
    const baseline = chart.querySelector('line');
    const points = chart.querySelectorAll('circle');
    expect(baseline).not.toBeNull();
    expect(points).toHaveLength(2);
    const zeroY = Number(baseline?.getAttribute('y1'));
    expect(Number(points[0]?.getAttribute('cy'))).toBeLessThan(zeroY);
    expect(Number(points[1]?.getAttribute('cy'))).toBeGreaterThan(zeroY);
  });

  it('renders row-specific currencies and exact decimal rates without relabeling them as home money', async () => {
    const fxResponse = structuredClone(answeredResponse);
    if (fxResponse.kind === 'answered') {
      fxResponse.evidence = [{
        id: 'fx-evidence',
        queryId: 'q1',
        title: 'FX evidence',
        kind: 'table',
        columns: [
          { key: 'chargedCurrency', label: 'Posted currency', type: 'status' },
          { key: 'chargedAmount', label: 'Posted amount', type: 'money' },
          { key: 'bankRate', label: 'Bank rate', type: 'decimal' }
        ],
        rows: [{
          chargedCurrency: 'TZS',
          chargedAmount: '270000.00',
          bankRate: '2650.000000'
        }],
        coverage: context.coverage,
        truncated: false
      }];
    }
    const fetchMock = vi.fn((input: RequestInfo | URL) => String(input) === '/api/ask/status'
      ? json({ enabled: true, available: true, reason: null })
      : json(fxResponse));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(AskPanel, { props: { currency: 'CAD' } });
    const textbox = await screen.findByRole('textbox', { name: 'Question' });
    await user.type(textbox, 'Show FX evidence');
    await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));

    expect(await screen.findByText('270,000.00')).toBeTruthy();
    expect(screen.getByText('2,650.000000')).toBeTruthy();
    expect(screen.queryByText('CAD 270,000.00')).toBeNull();
  });

  it('does not render provider-controlled external drill-down URLs', async () => {
    const unsafeResponse = structuredClone(answeredResponse);
    if (unsafeResponse.kind === 'answered') {
      unsafeResponse.evidence[0]!.drilldownPath = 'javascript:alert(1)';
    }
    const fetchMock = vi.fn((input: RequestInfo | URL) => String(input) === '/api/ask/status'
      ? json({ enabled: true, available: true, reason: null })
      : json(unsafeResponse));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(AskPanel);
    const textbox = await screen.findByRole('textbox', { name: 'Question' });
    await user.type(textbox, 'Show evidence');
    await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));
    await screen.findByRole('heading', { name: 'Answer' });

    expect(screen.queryByRole('link', { name: 'Open supporting records' })).toBeNull();
  });

  it('retains only three validated plans and clears tab memory on reset and scope change', async () => {
    const requests: Record<string, unknown>[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/ask/status') {
        return json({ enabled: true, available: true, reason: null });
      }
      requests.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return json(answeredResponse);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    const view = render(AskPanel, { props: { market: 'ALL', currency: 'CAD' } });
    const textbox = await screen.findByRole('textbox', { name: 'Question' });

    for (const nextQuestion of ['First question', 'Second question', 'Third question', 'Fourth question']) {
      await user.clear(textbox);
      await user.type(textbox, nextQuestion);
      await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));
      await waitFor(() => expect(requests).toHaveLength(['First question', 'Second question', 'Third question', 'Fourth question'].indexOf(nextQuestion) + 1));
    }

    expect((requests[3]?.history as unknown[])).toHaveLength(3);
    expect((requests[3]?.history as { question: string }[]).map((turn) => turn.question)).toEqual([
      'First question', 'Second question', 'Third question'
    ]);
    expect(screen.getByText('3 prior validated plans in this tab')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'New conversation' }));
    expect((textbox as HTMLTextAreaElement).value).toBe('');
    expect(screen.getByText('No prior question context')).toBeTruthy();

    await user.type(textbox, 'Scoped question');
    await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));
    await waitFor(() => expect(requests).toHaveLength(5));
    expect(requests[4]?.history).toEqual([]);

    await view.rerender({ market: 'TZ', currency: 'TZS' });
    expect(await screen.findByText(/Conversation cleared because/)).toBeTruthy();
    expect((textbox as HTMLTextAreaElement).value).toBe('');
    expect(screen.queryByText('Inspect normalized queries')).toBeNull();
  });

  it('offers clarification choices, carries the validated clarification plan, and retries operational errors', async () => {
    const requests: Record<string, unknown>[] = [];
    let postCount = 0;
    const clarifyPlan: AskPlanV1 = {
      version: 1,
      disposition: 'clarify',
      prompt: 'Which account?',
      choices: [{ label: 'Everyday chequing' }, { label: 'Travel rewards' }]
    };
    const clarification: AskResponse = {
      kind: 'clarification_required',
      requestId: '22222222-2222-4222-8222-222222222222',
      prompt: 'Which account should Ledger use?',
      choices: [{ label: 'Everyday chequing' }, { label: 'Travel rewards' }],
      plan: clarifyPlan
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/ask/status') {
        return json({ enabled: true, available: true, reason: null });
      }
      postCount += 1;
      requests.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      if (postCount === 1) {
        return json({ error: { code: 'ask_planning_failed', message: 'The safe plan could not be validated.' } }, 502);
      }
      if (postCount === 2) return json(clarification);
      return json(answeredResponse);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(AskPanel);
    const textbox = await screen.findByRole('textbox', { name: 'Question' });
    await user.type(textbox, 'Show account spending');
    await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));
    expect(await screen.findByText('The safe plan could not be validated.')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('heading', { name: 'Which account should Ledger use?' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Travel rewards' }));
    expect((textbox as HTMLTextAreaElement).value).toBe('Show account spending (Travel rewards)');
    await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));
    await screen.findByRole('heading', { name: 'Answer' });

    expect(requests[2]?.history).toEqual([{ question: 'Show account spending', plan: clarifyPlan }]);
  });

  it('submits a local clarification token with the unchanged question and no decorated database label', async () => {
    const requests: Record<string, unknown>[] = [];
    const localPlan: AskExecutePlanV1 = {
      version: 1,
      disposition: 'execute',
      queries: [{
        id: 'q1',
        dataset: 'aggregate',
        market: 'ALL',
        date: { kind: 'preset', value: 'last_month' },
        entity: { kind: 'account', term: 'Daily card' },
        metrics: ['spending'],
        groupBy: 'total',
        comparison: 'none',
        limit: 20
      }]
    };
    const entityToken = 'a'.repeat(64);
    const decoratedLabel = 'Daily card · Tanzania · •••• 9876';
    const clarification: AskResponse = {
      kind: 'clarification_required',
      requestId: '22222222-2222-4222-8222-222222222222',
      prompt: 'Which matching account should Ledger use?',
      choices: [{
        label: decoratedLabel,
        localSelection: { queryId: 'q1', entityToken }
      }],
      plan: localPlan
    };
    let postCount = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/ask/status') {
        return json({ enabled: true, available: true, reason: null });
      }
      postCount += 1;
      requests.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return json(postCount === 1 ? clarification : answeredResponse);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(AskPanel);
    const textbox = await screen.findByRole('textbox', { name: 'Question' });
    const question = 'Show spending for Daily card';
    await user.type(textbox, question);
    await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));
    await screen.findByRole('heading', { name: clarification.prompt });
    await user.click(screen.getByRole('button', { name: decoratedLabel }));
    await screen.findByRole('heading', { name: 'Answer' });

    expect(requests).toHaveLength(2);
    expect(requests[1]).toMatchObject({
      question,
      history: [],
      localSelection: { plan: localPlan, queryId: 'q1', entityToken }
    });
    expect(JSON.stringify(requests[1])).not.toContain(decoratedLabel);
    expect(JSON.stringify(requests[1])).not.toContain('•••• 9876');
    expect((textbox as HTMLTextAreaElement).value).toBe(question);
  });

  it('discards a stale response that arrives after a scope reset', async () => {
    let releaseRequest = (_response: Response) => {};
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input) === '/api/ask/status') {
        return json({ enabled: true, available: true, reason: null });
      }
      return new Promise<Response>((resolve) => {
        releaseRequest = resolve;
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    const view = render(AskPanel, { props: { market: 'ALL', currency: 'CAD' } });

    const textbox = await screen.findByRole('textbox', { name: 'Question' });
    await user.type(textbox, 'Show spending');
    await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));
    await screen.findByRole('button', { name: 'Cancel' });

    await view.rerender({ market: 'TZ', currency: 'TZS' });
    expect(await screen.findByText(/Conversation cleared because/)).toBeTruthy();
    releaseRequest(new Response(JSON.stringify(answeredResponse), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.queryByRole('heading', { name: 'Answer' })).toBeNull();
    expect(screen.getByText('No prior question context')).toBeTruthy();
  });

  it('aborts an in-flight request from the Cancel control', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/ask/status') {
        return json({ enabled: true, available: true, reason: null });
      }
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(AskPanel);
    const textbox = await screen.findByRole('textbox', { name: 'Question' });
    await user.type(textbox, 'Show spending');
    await user.click(screen.getByRole('button', { name: 'Ask Ledger' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(await screen.findByText('Ask request cancelled.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Ask Ledger' }) as HTMLButtonElement).disabled).toBe(false);
  });
});
