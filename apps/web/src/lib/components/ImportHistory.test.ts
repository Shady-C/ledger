/** @vitest-environment jsdom */

import { cleanup, render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { JobResponse } from '@ledger/shared-types';

import ImportHistory from './ImportHistory.svelte';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const needsSupportId = '11111111-1111-4111-8111-111111111111';
const doneId = '22222222-2222-4222-8222-222222222222';
const failedId = '33333333-3333-4333-8333-333333333333';
const digest = `${'a'.repeat(61)}c99`;
const csvDigest = `${'b'.repeat(61)}d77`;

const jobs = [
  {
    id: needsSupportId,
    kind: 'ingest' as const,
    status: 'needs_ai' as const,
    createdAt: '2026-07-26T07:18:00.000Z',
    finishedAt: '2026-07-26T07:18:10.000Z',
    retryCount: 0,
    maxRetries: 3
  },
  {
    id: doneId,
    kind: 'ingest' as const,
    status: 'done' as const,
    createdAt: '2026-07-25T07:18:00.000Z',
    finishedAt: '2026-07-25T07:18:10.000Z',
    retryCount: 1,
    maxRetries: 3
  },
  {
    id: failedId,
    kind: 'ingest' as const,
    status: 'failed' as const,
    createdAt: '2026-07-24T07:18:00.000Z',
    finishedAt: '2026-07-24T07:18:10.000Z',
    retryCount: 2,
    maxRetries: 3
  }
];

function json(value: unknown) {
  return Promise.resolve(new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'content-type': 'application/json' }
  }));
}

describe('ImportHistory', () => {
  it('uses truthful terminal copy and only shows retries for retryable states', () => {
    render(ImportHistory, { props: { jobs } });

    expect(screen.getByText('Needs format support')).toBeTruthy();
    expect(screen.queryByText('Needs mapping review')).toBeNull();
    expect(screen.queryByText('0/3 retries')).toBeNull();
    expect(screen.queryByText('1/3 retries')).toBeNull();
    expect(screen.getByText('2/3 retries')).toBeTruthy();
  });

  it('shows a privacy-safe statement label without exposing the stored digest', async () => {
    const detail: JobResponse = {
      id: needsSupportId,
      kind: 'ingest',
      status: 'needs_ai',
      createdAt: '2026-07-26T07:18:00.000Z',
      finishedAt: '2026-07-26T07:18:10.000Z',
      retryCount: 0,
      maxRetries: 3,
      error: null,
      result: {
        added: 0,
        skipped: 0,
        files: [
          {
            fileKey: `statements/account-id/${digest}.pdf`,
            adapter: 'pdf_table',
            status: 'needs_ai',
            added: 0,
            skipped: 0,
            statementId: null,
            reconciliation: null,
            reason: 'deterministic PDF table was not usable: CSV header requires date and amount columns'
          },
          {
            fileKey: `statements/account-id/${csvDigest}.csv`,
            adapter: 'ai_column_map',
            status: 'needs_ai',
            added: 0,
            skipped: 0,
            statementId: null,
            reconciliation: null,
            reason: 'AI column mapping could not be validated'
          }
        ]
      }
    };
    vi.stubGlobal('fetch', vi.fn(() => json(detail)));
    const user = userEvent.setup();

    render(ImportHistory, { props: { jobs: [jobs[0]!] } });
    await user.click(screen.getByRole('button', { name: /Needs format support/i }));

    expect(await screen.findByText('PDF statement · …c99')).toBeTruthy();
    expect(screen.getByText('CSV statement · …d77')).toBeTruthy();
    expect(screen.getByText('pdf_table · needs format support')).toBeTruthy();
    expect(screen.getByText('This PDF layout could not be parsed safely.')).toBeTruthy();
    expect(screen.getByText('This statement layout could not be parsed safely.')).toBeTruthy();
    expect(screen.queryByText(/CSV header requires/i)).toBeNull();
    expect(screen.queryByText(/AI column mapping/i)).toBeNull();
    expect(screen.queryByText(`${digest}.pdf`)).toBeNull();
    expect(document.body.textContent).not.toContain(digest);
    expect(document.body.textContent).not.toContain(csvDigest);
  });
});
