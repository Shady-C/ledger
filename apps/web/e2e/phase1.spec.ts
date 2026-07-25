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
const recurringId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const findingId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

type MockState = {
  partial?: boolean;
  transactionUrl?: string;
  transactionPatch?: unknown;
  accountPatch?: unknown;
  proposalDecision?: unknown;
  importStarted?: boolean;
  baseJobStarted?: boolean;
  activeBaseCurrency?: string;
  targetBaseCurrency?: string;
  baseCurrencyRequest?: unknown;
  mismatchOnce?: boolean;
  accountReads?: number;
  balanceReads?: number;
  findingDecision?: unknown;
  settingsPatch?: unknown;
  transactionDetailRead?: boolean;
  transactionDetailUrl?: string;
  transactionItems?: Record<string, unknown>[];
  accountItems?: typeof accounts;
  marketProfile?: 'CA' | 'TZ' | null;
  analyticsRebuilding?: boolean;
  insightsUrls?: string[];
};

const accounts = [
  {
    id: assetId,
    displayName: 'Everyday chequing',
    institutionId,
    institutionName: 'Northstar Bank',
    kind: 'chequing',
    nativeCurrency: 'CAD',
    marketCode: 'CA',
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
    marketCode: 'TZ',
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
  originalAmount: null,
  originalCurrency: null,
  amountBase: '12.40',
  currencyBase: 'CAD',
  fxRate: '1.00',
  fxRateDate: '2026-07-19',
  fxFeeAmountNative: null,
  isFxFee: false,
  valuationStatus: 'valued',
  conversionIndicators: [],
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

    if (url.pathname.startsWith('/api/insights/') && method === 'GET') {
      state.insightsUrls = [...(state.insightsUrls ?? []), request.url()];
    }

    if (url.pathname === '/api/accounts' && method === 'GET') {
      state.accountReads = (state.accountReads ?? 0) + 1;
      const market = url.searchParams.get('market');
      return json({
        accounts: market ? (state.accountItems ?? accounts).filter((account) => account.marketCode === market) : (state.accountItems ?? accounts),
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
    if (url.pathname === '/api/settings' && method === 'GET') return json({ baseCurrency: state.activeBaseCurrency ?? 'CAD', marketProfile: state.marketProfile ?? null, updatedAt: '2026-07-20T12:00:00.000Z' });
    if (url.pathname === '/api/settings' && method === 'PATCH') {
      state.settingsPatch = request.postDataJSON();
      return json({ baseCurrency: state.activeBaseCurrency ?? 'CAD', marketProfile: (state.settingsPatch as { marketProfile: string }).marketProfile, updatedAt: '2026-07-20T12:00:00.000Z' });
    }
    if (url.pathname === '/api/settings/base-currency' && method === 'POST') {
      state.baseJobStarted = true;
      state.baseCurrencyRequest = request.postDataJSON();
      state.targetBaseCurrency = (state.baseCurrencyRequest as { baseCurrency: string }).baseCurrency;
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
    if (url.pathname === '/api/analytics/fx') return json({
      baseCurrency: 'CAD', status: 'complete', totalExplicitFeeBase: '3.00',
      totalEstimatedMarkupBase: '5.42', totalFxCostBase: '8.42', missingRateCount: 0,
      transactions: [{
        transactionId,
        accountId: cardId,
        accountName: 'Travel rewards',
        bookedDate: '2026-07-20',
        description: 'USD software purchase',
        foreignAmount: '-100.00',
        foreignCurrency: 'USD',
        chargedAmountNative: '-142.00',
        nativeCurrency: 'CAD',
        bankAppliedRate: '1.39000000',
        marketRate: '1.35000000',
        marketRateDate: '2026-07-19',
        marketRateSource: 'fixture',
        markupPercent: '2.9630',
        explicitFeeNative: '3.00',
        explicitFeeBase: '3.00',
        estimatedMarkupNative: '5.42',
        estimatedMarkupBase: '5.42',
        isStandaloneFee: false
      }]
    });

    if (url.pathname === '/api/insights/summary' && method === 'GET') {
      if (state.analyticsRebuilding) return json({ error: { code: 'analytics_rebuilding', message: 'Analytics are rebuilding for TZS.' } }, 503);
      return json({
      baseCurrency: 'CAD', range: { from: '2025-08-01', to: '2026-07-24' },
      coverage: {
        status: state.partial ? 'partial' : 'complete',
        valuedTransactionCount: 12,
        unvaluedTransactionCount: state.partial ? 1 : 0,
        unvaluedByCurrency: state.partial ? [{ currency: 'TZS', transactionCount: 1, amountNative: '-270000.00' }] : []
      },
      totals: { inflow: '5500.00', outflow: '2500.00', spending: '2200.00', netCashflow: '3000.00' },
      spendingMonthOverMonth: { current: '220.00', previous: '200.00', change: '20.00', changePercent: '10.00' },
      spendingYearOverYear: null,
      recurring: { activeSeries: 1, overdueSeries: 0, expectedMonthlyAmount: '25.00' },
      findings: { new: 1, confirmed: 0, dismissed: 0, resolved: 0, unread: 1 },
      latestRun: null
      });
    }
    if (url.pathname === '/api/insights/trends' && method === 'GET') return json({
      baseCurrency: 'CAD', range: { from: '2025-08-01', to: '2026-07-24' }, groupBy: url.searchParams.get('groupBy') ?? 'ledger',
      coverage: { status: 'complete', valuedTransactionCount: 12, unvaluedTransactionCount: 0, unvaluedByCurrency: [] },
      points: [{ period: '2026-07-01', dimensionType: 'ledger', dimensionId: null, dimensionName: 'Ledger', inflow: '5500.00', outflow: '2500.00', spending: '2200.00', netCashflow: '3000.00', trailingAverageSpending: '2100.00', trailingMedianSpending: '2050.00', monthOverMonth: { current: '2200.00', previous: '2000.00', change: '200.00', changePercent: '10.00' }, yearOverYear: null, coverageStatus: 'complete', missingValuationCount: 0 }],
      movers: { positive: [], negative: [] }
    });
    if (url.pathname === '/api/insights/seasonality' && method === 'GET') return json({
      baseCurrency: 'CAD', range: { from: '2025-08-01', to: '2026-07-24' }, status: 'insufficient_history', historyMonths: 6, requiredHistoryMonths: 12,
      coverage: { status: 'complete', valuedTransactionCount: 12, unvaluedTransactionCount: 0, unvaluedByCurrency: [] }, months: []
    });
    if (url.pathname === '/api/insights/recurring' && method === 'GET') return json({
      baseCurrency: 'CAD', range: { from: '2025-08-01', to: '2026-07-24' }, page: 1, pageSize: 25, total: 1, totalPages: 1,
      series: [{ id: recurringId, merchantId: null, merchantName: 'Stream Co', accountId: cardId, accountName: 'Travel rewards', direction: 'spend', cadence: 'monthly', status: 'detected', confidence: '0.9500', comparisonBasis: 'base', expectedAmount: '25.00', currency: 'CAD', occurrenceCount: 3, firstOccurrenceDate: '2026-05-01', lastOccurrenceDate: '2026-07-01', expectedNextDate: '2026-08-01', overdue: false, latestChangePercent: '0.00', userCorrected: false, occurrences: [] }]
    });
    if (url.pathname === `/api/insights/recurring/${recurringId}` && method === 'PATCH') return json({ series: {} });
    if (url.pathname === '/api/insights/findings' && method === 'GET') return json({
      page: 1, pageSize: 25, total: 1, totalPages: 1,
      findings: [{ id: findingId, type: 'unusual_amount', status: 'new', severity: 'warning', title: 'Unusual transaction amount', summary: 'The amount is above its stable merchant baseline.', accountId: cardId, accountName: 'Travel rewards', categoryId, categoryName: 'Dining', merchantId: null, merchantName: 'Coffee House', recurringSeriesId: null, detectorFingerprint: 'fixture-fingerprint', evidence: { amountBase: '125.00', baselineMedian: '20.00', threshold: '3.5' }, firstSeenAt: '2026-07-20T12:00:00.000Z', lastSeenAt: '2026-07-20T12:00:00.000Z', reviewedAt: null }]
    });
    if (url.pathname === `/api/insights/findings/${findingId}` && method === 'PATCH') {
      state.findingDecision = request.postDataJSON();
      return json({ finding: {} });
    }
    if (url.pathname === '/api/insights/settings' && method === 'GET') return json({ settings: { sensitivity: 'balanced', updatedAt: '2026-07-20T12:00:00.000Z' } });
    if (url.pathname === '/api/insights/settings' && method === 'PATCH') return json({ settings: { sensitivity: request.postDataJSON().sensitivity, updatedAt: '2026-07-20T12:00:00.000Z' } });
    if (url.pathname === '/api/insights/rebuild' && method === 'POST') return json({ jobId, kind: 'analytics_refresh', status: 'queued' }, 202);

    if (url.pathname === '/api/transactions' && method === 'GET') {
      state.transactionUrl = request.url();
      const items = state.transactionItems ?? [transaction];
      return json({ items, page: Number(url.searchParams.get('page') ?? 1), pageSize: Number(url.searchParams.get('pageSize') ?? 25), total: items.length, totalPages: items.length === 0 ? 0 : 1 });
    }
    if (url.pathname === `/api/transactions/${transactionId}` && method === 'GET') {
      state.transactionDetailRead = true;
      state.transactionDetailUrl = request.url();
      return json({
        transaction: { ...transaction, conversionIndicators: ['fx'] },
        conversionEvidence: {
          indicators: ['fx'], valuationStatus: 'valued', reportingRate: '1.00000000', reportingRateDate: '2026-07-19',
          bankAppliedRate: '1.39000000', referenceRate: '1.35000000', referenceRateDate: '2026-07-19',
          referenceRateSource: 'fixture', explicitFeeNative: '3.00', explicitFeeBase: '3.00',
          estimatedMarkupNative: '5.42', estimatedMarkupBase: '5.42',
          runningBalanceNative: '1200.00', runningBalanceBase: '1200.00'
        }
      });
    }
    if (url.pathname === `/api/transactions/${transactionId}` && method === 'PATCH') {
      state.transactionPatch = request.postDataJSON();
      return json({ transaction: { id: transactionId, categoryId: categoryTwoId, categoryName: 'Other', categorySource: 'user_transaction', categoryConfidence: '1.00' }, merchantTransactionsUpdated: 1 });
    }

    if (url.pathname === '/api/jobs' && method === 'GET') return json({ jobs: [{ id: jobId, kind: 'ingest', status: 'done', createdAt: '2026-07-20T12:00:00.000Z', finishedAt: '2026-07-20T12:00:02.000Z', retryCount: 0, maxRetries: 3 }], page: 1, pageSize: 25, total: 1, totalPages: 1 });
    if (url.pathname.startsWith('/api/jobs/') && method === 'GET') {
      if (state.baseJobStarted) {
        state.activeBaseCurrency = state.targetBaseCurrency ?? 'TZS';
        return json({
          id: url.pathname.split('/').at(-1), kind: 'base_currency_rebuild', status: 'done', createdAt: '2026-07-20T12:00:00.000Z', finishedAt: '2026-07-20T12:00:02.000Z', retryCount: 0, maxRetries: 3, error: null,
          result: { previousBaseCurrency: 'CAD', targetBaseCurrency: state.activeBaseCurrency, transactionsUpdated: 1, settingsUpdated: true }
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

test('all focused pages support direct loads', async ({ page }) => {
  await mockLedger(page);
  for (const [path, heading] of [
    ['/', 'Know where you stand.'],
    ['/transactions', 'Every transaction, traceable.'],
    ['/accounts', 'Assets and credit, separated.'],
    ['/categories', 'Automation, with the final say yours.'],
    ['/insights', 'See the pattern. Inspect the proof.'],
    ['/imports', 'From statement to reconciled record.'],
    ['/more', 'Everything else, close at hand.'],
    ['/settings', 'Settings, without the clutter.']
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
  }
});

test('mobile navigation uses Home, Activity, Insights, and More', async ({ page }) => {
  await mockLedger(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Mobile navigation' });
  await expect(nav).toBeVisible();
  await expect(nav.getByRole('link')).toHaveCount(4);
  await nav.getByRole('link', { name: 'More' }).click();
  await expect(page).toHaveURL(/\/more$/);
  await page.getByRole('link', { name: /Accounts/ }).click();
  await expect(page).toHaveURL(/\/accounts$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Assets and credit, separated.' })).toBeVisible();
});

test('dashboard identifies partial net worth', async ({ page }) => {
  await mockLedger(page, { partial: true });
  await page.goto('/');
  await expect(page.getByText('Net worth is partial.')).toBeVisible();
  await expect(page.getByText(/1 account is excluded/)).toBeVisible();
  await expect(page.getByText('Historical CAD analytics are partial.')).toHaveCount(0);
});

test('Insights separates actual FX fees from estimated rate markup', async ({ page }) => {
  await mockLedger(page);
  await page.goto('/insights');
  await page.getByRole('tab', { name: 'FX' }).click();
  await expect(page.getByText('FX rate and cost evidence')).toBeVisible();
  await expect(page.getByText('Bank-applied rate', { exact: true })).toBeVisible();
  await expect(page.getByText('Reference rate', { exact: true })).toBeVisible();
  await expect(page.getByText('Actual fee', { exact: true })).toBeVisible();
  await expect(page.locator('.fx-list dt').filter({ hasText: /^Estimated markup$/ })).toBeVisible();
});

test('Home stays focused on net worth, accounts, and recent activity', async ({ page }) => {
  await mockLedger(page);
  await page.goto('/');
  await expect(page.locator('.net-worth strong')).toContainText('3,000.00');
  await expect(page.getByRole('heading', { name: 'Your accounts' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Recent transactions' })).toBeVisible();
  await expect(page.getByText('Analytics health')).toHaveCount(0);
  await expect(page.getByText('FX rate and cost evidence')).toHaveCount(0);
  await expect(page.getByRole('meter')).toHaveCount(0);
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

test('transaction rows show one posted amount and open conversion evidence on demand', async ({ page }) => {
  const state: MockState = {
    transactionItems: [
      {
        ...transaction,
        amountNative: '-270000.00',
        currencyNative: 'TZS',
        originalAmount: '-100.00',
        originalCurrency: 'USD',
        amountBase: '-142.90',
        fxRate: '0.00052926',
        fxFeeAmountNative: '5000.00',
        conversionIndicators: ['fx'],
        runningBalance: '730000.00',
        runningBalanceNative: '730000.00',
        runningBalanceBase: '386.00'
      },
      {
        ...transaction,
        id: '55555555-5555-4555-8555-555555555556',
        description: 'Pending USD valuation',
        amountNative: '-40.00',
        currencyNative: 'USD',
        originalAmount: null,
        originalCurrency: null,
        amountBase: null,
        fxRate: null,
        fxRateDate: null,
        fxFeeAmountNative: null,
        valuationStatus: 'pending_fx',
        conversionIndicators: ['pending'],
        runningBalance: '960.00',
        runningBalanceNative: '960.00',
        runningBalanceBase: null
      },
      {
        ...transaction,
        id: '55555555-5555-4555-8555-555555555557',
        description: 'Reporting-only conversion',
        amountNative: '-40.00',
        currencyNative: 'USD',
        amountBase: '-55.00',
        conversionIndicators: ['converted']
      },
      {
        ...transaction,
        id: '55555555-5555-4555-8555-555555555558',
        description: 'Pending merchant conversion',
        merchantName: null,
        amountNative: '-40000.00',
        currencyNative: 'TZS',
        originalAmount: '-16.00',
        originalCurrency: 'USD',
        amountBase: null,
        fxRate: null,
        fxRateDate: null,
        valuationStatus: 'pending_fx',
        conversionIndicators: ['fx', 'pending'],
        runningBalance: '920000.00',
        runningBalanceNative: '920000.00',
        runningBalanceBase: null
      }
    ]
  };
  await mockLedger(page, state);
  await page.goto('/transactions?market=TZ');
  await expect(page.getByText('FX').first()).toBeVisible();
  await expect(page.getByText('Converted')).toBeVisible();
  await expect(page.getByText('Pending', { exact: true }).first()).toBeVisible();
  const pendingFxRow = page.getByRole('row').filter({ hasText: 'Pending merchant conversion' });
  await expect(pendingFxRow.getByText('FX', { exact: true })).toBeVisible();
  await expect(pendingFxRow.getByText('Pending', { exact: true })).toBeVisible();
  await expect(page.getByText('Running balance')).toHaveCount(0);
  const detailButton = page.getByRole('button', { name: /View conversion details for Coffee House/ }).first();
  await detailButton.click();
  await expect(page.getByRole('dialog', { name: 'Conversion details' })).toBeVisible();
  await expect(page.getByText('Bank-applied rate')).toBeVisible();
  await expect.poll(() => state.transactionDetailRead).toBe(true);
  await expect.poll(() => state.transactionDetailUrl ?? '').toContain('market=TZ');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Conversion details' })).toHaveCount(0);
  await expect(detailButton).toBeFocused();

  await page.setViewportSize({ width: 390, height: 844 });
  await detailButton.click();
  await expect(page.getByRole('dialog', { name: 'Conversion details' })).toBeVisible();
  await expect.poll(async () => Math.round((await page.locator('.drawer').boundingBox())?.width ?? 0)).toBe(390);
  await page.getByRole('button', { name: 'Close conversion details' }).click();
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
  await expect(page.getByRole('meter', { name: 'Travel rewards utilization' })).toBeVisible();
  await page.locator('.credit-card').getByRole('button', { name: 'Edit' }).click();
  await expect(page.getByRole('heading', { name: 'Edit Travel rewards' })).toBeVisible();
  await page.getByLabel('Credit limit (CAD)').fill('7200.00');
  await page.getByRole('button', { name: 'Save account' }).click();
  await expect.poll(() => state.accountPatch).toMatchObject({ creditLimit: '7200.00', kind: 'credit_card', nativeCurrency: 'CAD' });
});

test('settings keep market profile separate from stable home currency', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Market profile' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Home currency', exact: true })).toBeVisible();
  await page.getByLabel('Default market').selectOption('TZ');
  await page.getByRole('button', { name: 'Save profile' }).click();
  await expect.poll(() => state.settingsPatch).toEqual({ marketProfile: 'TZ' });
  await expect(page.getByLabel('Target home currency')).toHaveValue('CAD');
});

test('home currency changes require explicit Advanced confirmation', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto('/settings');
  await page.getByLabel('Target home currency').selectOption('TZS');
  await expect(page.getByRole('button', { name: 'Change to TZS' })).toBeDisabled();
  await page.getByLabel(/I understand Insights will rebuild/).check();
  await page.getByRole('button', { name: 'Change to TZS' }).click();
  await expect.poll(() => state.baseCurrencyRequest).toEqual({ baseCurrency: 'TZS', confirmed: true });
  await expect(page.getByText(/Home currency changed to TZS/)).toBeVisible();
});

test('market scope is written to the URL, remembered, and sent to data APIs', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto(`/transactions?accountId=${assetId}`);
  await page.getByRole('button', { name: 'Tanzania', pressed: false }).click();
  await expect(page).toHaveURL(/market=TZ/);
  await expect(page.getByLabel('Filter by account')).toHaveValue('');
  await expect.poll(() => state.transactionUrl ?? '').toContain('market=TZ');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('ledger.market'))).toBe('TZ');
});

test('market profile supplies the first-visit scope when URL and storage are absent', async ({ page }) => {
  const state: MockState = { marketProfile: 'TZ' };
  await mockLedger(page, state);
  await page.goto('/transactions');
  await expect(page.getByRole('button', { name: 'Tanzania' })).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => state.transactionUrl ?? '').toContain('market=TZ');
});

test('unassigned accounts are marked and can be classified without profile inference', async ({ page }) => {
  const state: MockState = {
    accountItems: [{ ...accounts[1], marketCode: null }],
    marketProfile: 'CA'
  };
  await mockLedger(page, state);
  await page.goto('/accounts?market=ALL');
  await expect(page.getByText('Market needed')).toBeVisible();
  await page.locator('.credit-card').getByRole('button', { name: 'Edit' }).click();
  await expect(page.getByLabel('Account market')).toHaveValue('');
  await page.getByLabel('Account market').selectOption('TZ');
  await page.getByRole('button', { name: 'Save account' }).click();
  await expect.poll(() => state.accountPatch).toMatchObject({ marketCode: 'TZ' });
});

test('insight findings expose evidence and explicit review actions', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto('/insights');
  await expect(page.getByText('Needs review')).toBeVisible();
  const findingsTab = page.getByRole('tab', { name: /Findings/ });
  await findingsTab.click();
  await expect(findingsTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('heading', { name: 'Unusual transaction amount' })).toBeVisible();
  await page.getByText('Calculation and evidence').click();
  await expect(page.getByText('125.00')).toBeVisible();
  await page.getByRole('button', { name: 'Dismiss' }).click();
  await expect.poll(() => state.findingDecision).toEqual({ status: 'dismissed' });
});

test('Insights filters reload every view and tabs support keyboard navigation', async ({ page }) => {
  const state: MockState = {};
  await mockLedger(page, state);
  await page.goto('/insights');
  await page.getByLabel('Account').selectOption(cardId);
  await expect.poll(() => state.insightsUrls?.some((url) => url.includes(`accountId=${cardId}`))).toBe(true);
  const overview = page.getByRole('tab', { name: 'Overview' });
  await overview.focus();
  await overview.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Trends' })).toHaveAttribute('aria-selected', 'true');
});

test('Insights remains usable without page-level overflow on a mobile viewport', async ({ page }) => {
  await mockLedger(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/insights');
  await expect(page.getByRole('tablist', { name: 'Insights views' })).toBeVisible();
  const findingsTab = page.getByRole('tab', { name: 'Findings 1' });
  await expect(findingsTab).toBeVisible();
  await findingsTab.click();
  await expect(page.getByRole('heading', { name: 'Unusual transaction amount' })).toBeVisible();
  await expect.poll(() => page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth
  )).toBe(true);
});

test('Insights explains the maintenance state during a home-currency rebuild', async ({ page }) => {
  await mockLedger(page, { analyticsRebuilding: true });
  await page.goto('/insights');
  await expect(page.getByText('Insights are rebuilding.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open Advanced settings' })).toBeVisible();
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
