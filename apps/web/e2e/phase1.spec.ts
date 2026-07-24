import { expect, test, type Page } from '@playwright/test';

const assetId = '11111111-1111-4111-8111-111111111111';
const cardId = '22222222-2222-4222-8222-222222222222';
const categoryId = '33333333-3333-4333-8333-333333333333';
const categoryTwoId = '44444444-4444-4444-8444-444444444444';
const transactionId = '55555555-5555-4555-8555-555555555555';
const institutionId = '66666666-6666-4666-8666-666666666666';
const proposalId = '77777777-7777-4777-8777-777777777777';
const jobId = '88888888-8888-4888-8888-888888888888';
const statementId = '99999999-9999-4999-8999-999999999999';

type MockState = {
  partial?: boolean;
  transactionUrl?: string;
  transactionPatch?: unknown;
  accountPatch?: unknown;
  proposalDecision?: unknown;
  importStarted?: boolean;
  baseJobStarted?: boolean;
  activeBaseCurrency?: string;
  mismatchOnce?: boolean;
  accountReads?: number;
  balanceReads?: number;
};

const accounts = [
  {
    id: assetId,
    displayName: 'Everyday chequing',
    institutionId,
    institutionName: 'Northstar Bank',
    kind: 'chequing',
    nativeCurrency: 'CAD',
    accountRefMasked: '•••• 1024',
    currentBalance: '4200.00',
    currentBalanceBase: '4200.00',
    baseCurrency: 'CAD',
    balanceBasis: 'balance',
    lastStatementDate: '2026-07-20',
    creditLimit: null,
    usedCredit: null,
    availableCredit: null,
    utilizationPercent: null
  },
  {
    id: cardId,
    displayName: 'Travel rewards',
    institutionId,
    institutionName: 'Northstar Bank',
    kind: 'credit_card',
    nativeCurrency: 'CAD',
    accountRefMasked: '•••• 4812',
    currentBalance: '1200.00',
    currentBalanceBase: '1200.00',
    baseCurrency: 'CAD',
    balanceBasis: 'balance',
    lastStatementDate: '2026-07-18',
    creditLimit: '6000.00',
    usedCredit: '1200.00',
    availableCredit: '4800.00',
    utilizationPercent: '20.00'
  }
];

const categories = [
  { id: categoryId, parentId: null, name: 'Dining', kind: 'spend', archivedAt: null, isProtected: false },
  { id: categoryTwoId, parentId: null, name: 'Other', kind: 'spend', archivedAt: null, isProtected: true }
];

const transaction = {
  id: transactionId,
  accountId: cardId,
  accountName: 'Travel rewards',
  bookedDate: '2026-07-19',
  postedDate: '2026-07-20',
  description: 'COFFEE HOUSE 1842',
  merchantName: 'Coffee House',
  categoryId,
  categoryName: 'Dining',
  categorySource: 'ai',
  categoryConfidence: '0.92',
  amountNative: '12.40',
  currencyNative: 'CAD',
  amountBase: '12.40',
  currencyBase: 'CAD',
  fxRate: '1.00',
  direction: 'debit',
  runningBalance: '1200.00',
  runningBalanceNative: '1200.00',
  runningBalanceBase: '1200.00',
  enrichment: {}
};

async function mockLedger(page: Page, state: MockState = {}) {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const json = (value: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(value)
    });

    if (url.pathname === '/api/accounts' && method === 'GET') {
      state.accountReads = (state.accountReads ?? 0) + 1;
      return json({
        accounts,
        creditUtilization: {
          baseCurrency: 'CAD',
          usedCreditBase: '1200.00',
          creditLimitBase: '6000.00',
          availableCreditBase: '4800.00',
          utilizationPercent: '20.00',
          includedAccountCount: 1,
          excludedAccounts: []
        }
      });
    }
    if (url.pathname === `/api/accounts/${cardId}` && method === 'PATCH') {
      state.accountPatch = request.postDataJSON();
      return json({ account: { ...accounts[1], ...(state.accountPatch as object) } });
    }
    if (url.pathname === '/api/accounts' && method === 'POST') return json({ account: accounts[0] }, 201);
    if (url.pathname === '/api/institutions' && method === 'GET') return json({ institutions: [{ id: institutionId, name: 'Northstar Bank' }] });
    if (url.pathname.startsWith('/api/institutions') && method !== 'GET') return json({ institution: { id: institutionId, name: 'Northstar Bank' } });
    if (url.pathname === '/api/settings' && method === 'GET') return json({ baseCurrency: state.activeBaseCurrency ?? 'CAD', updatedAt: '2026-07-20T12:00:00.000Z' });
    if (url.pathname === '/api/settings/base-currency' && method === 'POST') {
      state.baseJobStarted = true;
      return json({ jobId, kind: 'base_currency_rebuild', status: 'queued' }, 202);
    }

    if (url.pathname === '/api/categories' && method === 'GET') return json({ categories });
    if (url.pathname === '/api/categories' && method === 'POST') return json({ category: categories[0] }, 201);
    if (url.pathname === '/api/categories/unresolved' && method === 'GET') return json({ unresolved: [{
      merchantId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      merchantName: 'Corner Grocer',
      flowType: 'spend',
      transactionCount: 3,
      firstSeen: '2026-07-10',
      lastSeen: '2026-07-20'
    }] });
    if (url.pathname.startsWith('/api/categories/') && !url.pathname.includes('/proposals') && !url.pathname.endsWith('/categorize')) return json({ category: categories[0] });
    if (url.pathname === '/api/categories/proposals' && method === 'GET') return json({ proposals: [{
      id: proposalId,
      opaqueKey: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      merchantId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      merchantName: 'Market Street Cafe',
      flowType: 'spend',
      proposedCategoryId: categoryId,
      proposedCategoryName: 'Dining',
      proposedCategoryKind: 'spend',
      confidence: '0.72',
      status: 'pending',
      provider: 'anthropic',
      model: 'claude-haiku-4-5',
      reviewedAt: null,
      createdAt: '2026-07-20T12:00:00.000Z'
    }] });
    if (url.pathname === `/api/categories/proposals/${proposalId}` && method === 'PATCH') {
      state.proposalDecision = request.postDataJSON();
      return json({ proposalId, status: 'accepted', categoryId, transactionsUpdated: 2 });
    }
    if (url.pathname === '/api/categories/categorize' && method === 'POST') return json({ jobId, kind: 'categorize', status: 'queued' }, 202);

    if (url.pathname === '/api/analytics/balance') {
      state.balanceReads = (state.balanceReads ?? 0) + 1;
      const currency = state.mismatchOnce && state.balanceReads === 1 ? 'USD' : 'CAD';
      return json({ currency, basis: 'balance', points: [{ date: '2026-07-19', balance: '3000.00' }, { date: '2026-07-20', balance: '3000.00' }] });
    }
    if (url.pathname === '/api/analytics/cashflow') return json({ currency: 'CAD', points: [{ period: '2026-07-01', inflow: '5500.00', outflow: '2500.00', cardPayments: '3000.00', net: '3000.00' }] });
    if (url.pathname === '/api/analytics/net-worth') return json({
      baseCurrency: 'CAD', valuationDate: '2026-07-20', status: state.partial ? 'partial' : 'complete',
      assets: '4200.00', liabilities: '1200.00', netWorth: '3000.00', accounts: [],
      excludedAccounts: state.partial ? [{ accountId: assetId, displayName: 'TZS wallet', reason: 'missing_fx_rate' }] : []
    });
    if (url.pathname === '/api/analytics/fx') return json({ baseCurrency: 'CAD', totalEstimatedFeeBase: '8.42', transactions: [] });

    if (url.pathname === '/api/transactions' && method === 'GET') {
      state.transactionUrl = request.url();
      return json({ items: [transaction], page: Number(url.searchParams.get('page') ?? 1), pageSize: Number(url.searchParams.get('pageSize') ?? 25), total: 1, totalPages: 1 });
    }
    if (url.pathname === `/api/transactions/${transactionId}` && method === 'PATCH') {
      state.transactionPatch = request.postDataJSON();
      return json({ transaction: { id: transactionId, categoryId: categoryTwoId, categoryName: 'Other', categorySource: 'user_transaction', categoryConfidence: '1.00' }, merchantTransactionsUpdated: 1 });
    }

    if (url.pathname === '/api/jobs' && method === 'GET') return json({ jobs: [{ id: jobId, kind: 'ingest', status: 'done', createdAt: '2026-07-20T12:00:00.000Z', finishedAt: '2026-07-20T12:00:02.000Z', retryCount: 0, maxRetries: 3 }], page: 1, pageSize: 25, total: 1, totalPages: 1 });
    if (url.pathname.startsWith('/api/jobs/') && method === 'GET') {
      if (state.baseJobStarted) {
        state.activeBaseCurrency = 'USD';
        return json({
          id: url.pathname.split('/').at(-1), kind: 'base_currency_rebuild', status: 'done', createdAt: '2026-07-20T12:00:00.000Z', finishedAt: '2026-07-20T12:00:02.000Z', retryCount: 0, maxRetries: 3, error: null,
          result: { previousBaseCurrency: 'CAD', targetBaseCurrency: 'USD', transactionsUpdated: 1, settingsUpdated: true }
        });
      }
      return json({
        id: url.pathname.split('/').at(-1), kind: 'ingest', status: 'done', createdAt: '2026-07-20T12:00:00.000Z', finishedAt: '2026-07-20T12:00:02.000Z', retryCount: 0, maxRetries: 3, error: null,
        result: { added: 1, skipped: 0, files: [{ fileKey: 'statements/sample.csv', adapter: 'generic_csv', status: 'done', added: 1, skipped: 0, statementId, reason: null, reconciliation: { status: 'ok', openingBalance: '100.00', transactionTotal: '12.40', calculatedClosing: '112.40', reportedClosing: '112.40', difference: '0.00', coverageGaps: [] } }] }
      });
    }
    if (url.pathname === '/api/ingest' && method === 'POST') {
      state.importStarted = true;
      return json({ jobId, status: 'queued' }, 202);
    }

    return json({ error: { code: 'not_mocked', message: `No mock for ${method} ${url.pathname}` } }, 404);
  });
}

test('all five focused pages support direct loads', async ({ page }) => {
  await mockLedger(page);
  for (const [path, heading] of [
    ['/', 'Know where you stand.'],
    ['/transactions', 'Every transaction, traceable.'],
    ['/accounts', 'Assets and credit, separated.'],
    ['/categories', 'Automation, with the final say yours.'],
    ['/imports', 'From statement to reconciled record.']
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
  }
});

test('mobile navigation reaches each focused page', async ({ page }) => {
  await mockLedger(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Mobile navigation' });
  await expect(nav).toBeVisible();
  await nav.getByRole('link', { name: 'Accounts' }).click();
  await expect(page).toHaveURL(/\/accounts$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Assets and credit, separated.' })).toBeVisible();
});

test('dashboard identifies partial net worth', async ({ page }) => {
  await mockLedger(page, { partial: true });
  await page.goto('/');
  await expect(page.getByText('Net worth is partial.')).toBeVisible();
  await expect(page.getByText(/1 account is excluded/)).toBeVisible();
});

test('dashboard retries instead of rendering a mixed-base snapshot', async ({ page }) => {
  const state: MockState = { mismatchOnce: true };
  await mockLedger(page, state);
  await page.goto('/');
  await expect(page.locator('.net-worth strong')).toContainText('3,000.00');
  await expect.poll(() => state.accountReads ?? 0).toBeGreaterThanOrEqual(2);
  await expect(page.getByText(/Ledger valuation changed/)).toHaveCount(0);
});

test('transaction filters are restored from and written to the URL', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto(`/transactions?search=coffee&accountId=${cardId}&from=2026-07-01&to=2026-07-20&pageSize=10`);
  await expect(page.getByPlaceholder('Search descriptions or merchants')).toHaveValue('coffee');
  await expect(page.getByLabel('Filter by account')).toHaveValue(cardId);
  await expect(page.getByLabel('From')).toHaveValue('2026-07-01');
  await expect.poll(() => state.transactionUrl ?? '').toContain('pageSize=10');
  await page.getByLabel('Filter by direction').selectOption('debit');
  await expect(page).toHaveURL(/direction=debit/);
});

test('transaction category override sends the explicit scope', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto('/transactions');
  await page.getByRole('button', { name: /Change category for Coffee House/ }).click();
  await page.getByLabel('New category').selectOption(categoryTwoId);
  await page.getByRole('button', { name: 'This transaction' }).click();
  await expect.poll(() => state.transactionPatch).toEqual({ categoryId: categoryTwoId, applyToMerchant: false });
});

test('credit-card editing saves the native-currency limit', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto('/accounts');
  await page.locator('.credit-card').getByRole('button', { name: 'Edit' }).click();
  await expect(page.getByRole('heading', { name: 'Edit Travel rewards' })).toBeVisible();
  await page.getByLabel('Credit limit (CAD)').fill('7200.00');
  await page.getByRole('button', { name: 'Save account' }).click();
  await expect.poll(() => state.accountPatch).toMatchObject({ creditLimit: '7200.00', kind: 'credit_card', nativeCurrency: 'CAD' });
});

test('base-currency switch stays pending until the atomic rebuild completes', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto('/accounts');
  await expect(page.locator('.credit-card')).toBeVisible();
  await expect(page.getByText('Current consolidated valuation: CAD')).toBeVisible();
  await page.getByLabel('Display currency').selectOption('USD');
  await expect(page.getByLabel('Display currency')).toHaveValue('USD');
  await expect(page.getByRole('button', { name: 'Rebuild values' })).toBeEnabled();
  await page.getByRole('button', { name: 'Rebuild values' }).click();
  await expect.poll(() => state.baseJobStarted).toBe(true);
  await expect(page.getByText(/USD is now the active base currency/)).toBeVisible();
  await expect(page.getByText('Current consolidated valuation: USD')).toBeVisible();
});

test('category proposals require an explicit decision', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto('/categories');
  await expect(page.getByText('Corner Grocer')).toBeVisible();
  await expect(page.getByText('Market Street Cafe')).toBeVisible();
  await page.getByRole('button', { name: 'Accept' }).click();
  await expect.poll(() => state.proposalDecision).toEqual({ decision: 'accept' });
});

test('statement upload polls the accepted import job', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto('/imports');
  await page.getByLabel('Import into').selectOption(assetId);
  await page.locator('input[type="file"]').setInputFiles({ name: 'sample.csv', mimeType: 'text/csv', buffer: Buffer.from('date,description,amount\n2026-07-20,Coffee,12.40') });
  await page.getByRole('button', { name: 'Import 1' }).click();
  await expect.poll(() => state.importStarted).toBe(true);
  await expect(page.getByText('Import complete: 1 added')).toBeVisible();
});
