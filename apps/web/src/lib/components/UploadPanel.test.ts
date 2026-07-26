/** @vitest-environment jsdom */

import { cleanup, render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import UploadPanel from './UploadPanel.svelte';
import type { AccountView } from './phase1-types.js';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const account: AccountView = {
  id: '22222222-2222-4222-8222-222222222222',
  displayName: 'Everyday chequing',
  institutionId: null,
  institutionName: null,
  kind: 'chequing',
  nativeCurrency: 'CAD',
  marketCode: 'CA',
  accountRefMasked: '••••1234',
  currentBalance: '100.00',
  currentBalanceBase: '100.00',
  baseCurrency: 'CAD',
  balanceBasis: 'balance',
  lastStatementDate: null,
  creditLimit: null,
  usedCredit: null,
  availableCredit: null,
  utilizationPercent: null
};

function json(value: unknown) {
  return Promise.resolve(new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'content-type': 'application/json' }
  }));
}

describe('UploadPanel', () => {
  it('describes a needs_ai outcome as deterministic format support', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input) === '/api/ingest') {
        return json({ jobId: '11111111-1111-4111-8111-111111111111', status: 'queued' });
      }
      return json({
        id: '11111111-1111-4111-8111-111111111111',
        kind: 'ingest',
        status: 'needs_ai',
        result: { added: 0, skipped: 0, files: [] },
        error: null
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    const onComplete = vi.fn();
    const user = userEvent.setup();
    const view = render(UploadPanel, { props: { accounts: [account], onComplete } });
    const input = view.container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();

    await user.upload(input!, new File(['%PDF-1.7'], 'statement.pdf', { type: 'application/pdf' }));
    await user.click(screen.getByRole('button', { name: 'Import 1' }));

    expect(await screen.findByText('At least one statement needs format support before Ledger can safely import it.')).toBeTruthy();
    expect(screen.queryByText(/reviewed AI column map/i)).toBeNull();
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
  });
});
