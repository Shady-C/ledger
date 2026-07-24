<script lang="ts">
  import { onMount } from 'svelte';
  import type {
    AccountsResponse,
    BalanceResponse,
    CategoriesResponse,
    CashflowResponse,
    TransactionPage,
    TransactionSort
  } from '@ledger/shared-types';

  import AccountStrip from '$lib/components/AccountStrip.svelte';
  import BrandMark from '$lib/components/BrandMark.svelte';
  import TransactionsTable from '$lib/components/TransactionsTable.svelte';
  import UploadPanel from '$lib/components/UploadPanel.svelte';
  import BalanceChart from '$lib/charts/BalanceChart.svelte';
  import CashflowChart from '$lib/charts/CashflowChart.svelte';
  import { apiMessage, money } from '$lib/format.js';

  let accounts: AccountsResponse['accounts'] = [];
  let categories: CategoriesResponse['categories'] = [];
  let balance: BalanceResponse = { currency: 'CAD', points: [] };
  let cashflow: CashflowResponse = { currency: 'CAD', points: [] };
  let transactions: TransactionPage = { items: [], page: 1, pageSize: 25, total: 0, totalPages: 0 };
  let loadingSummary = true;
  let loadingTransactions = true;
  let pageError = '';
  let selectedAccount = '';
  let search = '';
  let direction = '';
  let categoryId = '';
  let sort: TransactionSort = 'booked_date_desc';
  let page = 1;

  $: currentAccount = accounts.find((account) => account.id === selectedAccount);
  $: currentBalance = currentAccount?.currentBalance ?? balance.points.at(-1)?.balance ?? '0';
  $: latestCashflow = cashflow.points.at(-1);

  function queryString(includePage = false) {
    const query = new URLSearchParams();
    if (selectedAccount) query.set('accountId', selectedAccount);
    if (search) query.set('search', search);
    if (direction) query.set('direction', direction);
    if (categoryId) query.set('categoryId', categoryId);
    if (sort !== 'booked_date_desc') query.set('sort', sort);
    if (includePage && page > 1) query.set('page', String(page));
    const encoded = query.toString();
    return encoded ? `?${encoded}` : '';
  }

  async function fetchJson<T>(url: string): Promise<T> {
    const response = await fetch(url, { headers: { accept: 'application/json' } });
    if (!response.ok) throw new Error(await apiMessage(response, 'Ledger data is temporarily unavailable.'));
    return response.json() as Promise<T>;
  }

  async function loadAccounts() {
    const [accountResult, categoryResult] = await Promise.all([
      fetchJson<AccountsResponse>('/api/accounts'),
      fetchJson<CategoriesResponse>('/api/categories')
    ]);
    accounts = accountResult.accounts;
    categories = categoryResult.categories;
  }

  async function loadAnalytics() {
    const suffix = selectedAccount ? `?accountId=${encodeURIComponent(selectedAccount)}` : '';
    [balance, cashflow] = await Promise.all([
      fetchJson<BalanceResponse>(`/api/analytics/balance${suffix}`),
      fetchJson<CashflowResponse>(`/api/analytics/cashflow${suffix}`)
    ]);
  }

  async function loadTransactions() {
    loadingTransactions = true;
    try {
      transactions = await fetchJson<TransactionPage>(`/api/transactions${queryString(true)}`);
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Transactions are temporarily unavailable.';
      transactions = { items: [], page, pageSize: 25, total: 0, totalPages: 0 };
    } finally {
      loadingTransactions = false;
    }
  }

  async function loadDashboard(refreshAccounts = false) {
    loadingSummary = true;
    pageError = '';
    try {
      if (refreshAccounts) await loadAccounts();
      await Promise.all([loadAnalytics(), loadTransactions()]);
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Ledger data is temporarily unavailable.';
      balance = { currency: balance.currency, points: [] };
      cashflow = { currency: cashflow.currency, points: [] };
    } finally {
      loadingSummary = false;
    }
  }

  async function selectAccount(id: string) {
    selectedAccount = id;
    page = 1;
    await loadDashboard();
  }

  async function applyFilters(filters: {
    search: string;
    accountId: string;
    categoryId: string;
    direction: string;
    sort: TransactionSort;
  }) {
    search = filters.search.trim();
    selectedAccount = filters.accountId;
    categoryId = filters.categoryId;
    direction = filters.direction;
    sort = filters.sort;
    page = 1;
    await loadDashboard();
  }

  async function changePage(next: number) {
    page = next;
    await loadTransactions();
  }

  onMount(async () => {
    try {
      await loadAccounts();
      await loadDashboard();
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Ledger is temporarily unavailable.';
      loadingSummary = false;
      loadingTransactions = false;
    }
  });
</script>

<svelte:head>
  <title>Ledger · Your financial record</title>
  <meta name="description" content="Import, reconcile, and inspect your self-hosted financial ledger." />
</svelte:head>

<header class="site-header">
  <a class="brand" href="/" aria-label="Ledger dashboard">
    <BrandMark />
    <span>Ledger</span>
  </a>
  <div class="privacy"><span aria-hidden="true"></span> Self-hosted & private</div>
</header>

<main>
  <section class="hero" aria-labelledby="page-title">
    <div class="hero-copy">
      <p class="kicker">Your financial record</p>
      <h1 id="page-title">Every number.<br /><em>Accounted for.</em></h1>
      <p class="lede">One deterministic ledger across your statements, with every balance traceable to its source.</p>
    </div>
    <div class="hero-metrics" aria-label="Ledger summary">
      <div>
        <span>Current balance</span>
        <strong>{loadingSummary ? '—' : money(currentBalance, currentAccount?.nativeCurrency ?? balance.currency)}</strong>
      </div>
      <div>
        <span>Latest net flow</span>
        <strong class:positive={Number(latestCashflow?.net ?? 0) >= 0}>
          {loadingSummary || !latestCashflow ? '—' : money(latestCashflow.net, cashflow.currency)}
        </strong>
      </div>
      <div>
        <span>Ledger records</span>
        <strong>{loadingTransactions ? '—' : transactions.total.toLocaleString()}</strong>
      </div>
    </div>
  </section>

  {#if pageError}
    <div class="error-banner" role="alert">
      <strong>We couldn’t refresh everything.</strong>
      <span>{pageError}</span>
      <button type="button" on:click={() => loadDashboard(true)}>Try again</button>
    </div>
  {/if}

  <AccountStrip
    {accounts}
    loading={loadingSummary && accounts.length === 0}
    selected={selectedAccount}
    onSelect={selectAccount}
  />

  <UploadPanel {accounts} onComplete={() => loadDashboard(true)} />

  <section class="charts" aria-label="Ledger analytics">
    <article class="chart-card balance-card">
      <div class="chart-heading">
        <div>
          <p>Daily position</p>
          <h2>Running balance</h2>
        </div>
        <span>{balance.currency}</span>
      </div>
      <BalanceChart points={balance.points} currency={balance.currency} loading={loadingSummary} />
    </article>

    <article class="chart-card">
      <div class="chart-heading">
        <div>
          <p>Period movement</p>
          <h2>Cash flow</h2>
        </div>
        <span>{cashflow.currency}</span>
      </div>
      <CashflowChart points={cashflow.points} currency={cashflow.currency} loading={loadingSummary} />
    </article>
  </section>

  <TransactionsTable
    data={transactions}
    {accounts}
    {categories}
    loading={loadingTransactions}
    {search}
    accountId={selectedAccount}
    {categoryId}
    {direction}
    {sort}
    onFilter={applyFilters}
    onPage={changePage}
  />
</main>

<footer>
  <span>Ledger</span>
  <p>Deterministic by design. Your financial arithmetic never leaves the code path.</p>
</footer>

<style>
  .site-header {
    display: flex;
    width: min(1180px, calc(100% - 2rem));
    margin: 0 auto;
    padding: 1.25rem 0;
    align-items: center;
    justify-content: space-between;
  }

  .brand {
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    color: var(--forest);
    font-size: 1rem;
    font-weight: 850;
    letter-spacing: -0.04em;
    text-decoration: none;
  }

  .privacy {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    color: var(--muted);
    font-size: 0.68rem;
    font-weight: 700;
  }

  .privacy span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #4eae86;
    box-shadow: 0 0 0 4px rgb(78 174 134 / 12%);
  }

  main {
    display: grid;
    width: min(1180px, calc(100% - 2rem));
    margin: 0 auto;
    gap: clamp(1.3rem, 3vw, 2.2rem);
  }

  .hero {
    display: grid;
    grid-template-columns: minmax(0, 1.1fr) minmax(360px, 0.9fr);
    gap: clamp(2rem, 7vw, 6rem);
    align-items: end;
    min-height: 350px;
    padding: clamp(2rem, 6vw, 4.8rem) 0 clamp(2rem, 5vw, 3.8rem);
  }

  .kicker {
    margin: 0 0 0.8rem;
    color: var(--coral);
    font-size: 0.72rem;
    font-weight: 850;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  h1 {
    margin: 0;
    color: var(--forest);
    font-size: clamp(3rem, 8vw, 6.2rem);
    font-weight: 740;
    line-height: 0.9;
    letter-spacing: -0.07em;
  }

  h1 em {
    color: var(--coral);
    font-family: Georgia, 'Times New Roman', serif;
    font-weight: 400;
    letter-spacing: -0.055em;
  }

  .lede {
    max-width: 49ch;
    margin: 1.25rem 0 0;
    color: var(--muted);
    font-size: 0.9rem;
    line-height: 1.65;
  }

  .hero-metrics {
    display: grid;
    border-top: 1px solid #cdd3cc;
  }

  .hero-metrics div {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem 0;
    border-bottom: 1px solid #cdd3cc;
  }

  .hero-metrics span {
    color: var(--muted);
    font-size: 0.7rem;
    font-weight: 750;
  }

  .hero-metrics strong {
    color: var(--forest);
    font-size: clamp(1.2rem, 2.5vw, 1.75rem);
    letter-spacing: -0.045em;
    font-variant-numeric: tabular-nums;
  }

  .hero-metrics strong.positive { color: #237a64; }

  .error-banner {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding: 0.8rem 1rem;
    color: #722f24;
    border: 1px solid #e7b9ab;
    border-radius: 12px;
    background: #fff0e9;
    font-size: 0.76rem;
  }

  .error-banner span { flex: 1; }
  .error-banner button {
    padding: 0.4rem 0.65rem;
    color: #722f24;
    border: 1px solid #d99f8e;
    border-radius: 7px;
    background: white;
    font-size: 0.7rem;
    font-weight: 800;
  }

  .charts {
    display: grid;
    grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.85fr);
    gap: 1rem;
  }

  .chart-card {
    min-width: 0;
    padding: clamp(1rem, 2.3vw, 1.5rem);
    border: 1px solid var(--line);
    border-radius: 22px;
    background: var(--paper);
    box-shadow: var(--shadow);
  }

  .chart-heading {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 0.7rem;
  }

  .chart-heading p,
  .chart-heading h2 { margin: 0; }
  .chart-heading p {
    margin-bottom: 0.2rem;
    color: var(--coral);
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }
  .chart-heading h2 { font-size: 1.25rem; letter-spacing: -0.035em; }
  .chart-heading > span {
    padding: 0.25rem 0.45rem;
    color: var(--muted);
    border-radius: 6px;
    background: #efeee8;
    font-size: 0.62rem;
    font-weight: 800;
  }

  footer {
    display: flex;
    width: min(1180px, calc(100% - 2rem));
    margin: 3rem auto 0;
    padding: 1.5rem 0 2.5rem;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    color: var(--muted);
    border-top: 1px solid #d8d9d2;
    font-size: 0.68rem;
  }
  footer span { color: var(--forest); font-weight: 850; }
  footer p { margin: 0; text-align: right; }

  @media (max-width: 900px) {
    .hero { grid-template-columns: 1fr; min-height: 0; }
    .hero-metrics { grid-template-columns: repeat(3, 1fr); }
    .hero-metrics div { display: grid; align-content: start; }
    .charts { grid-template-columns: 1fr; }
  }

  @media (max-width: 620px) {
    .site-header,
    main,
    footer { width: min(100% - 1.2rem, 1180px); }
    .hero { padding-top: 2.5rem; }
    .hero-metrics { grid-template-columns: 1fr; }
    .hero-metrics div { display: flex; }
    .error-banner { align-items: flex-start; flex-wrap: wrap; }
    .error-banner span { flex-basis: 70%; }
    footer { align-items: start; }
  }
</style>
