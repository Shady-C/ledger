<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import type {
    AccountsResponse,
    CategoriesResponse,
    TransactionCategoryUpdateResponse,
    TransactionSort
  } from '@ledger/shared-types';

  import TransactionsTable from '$lib/components/TransactionsTable.svelte';
  import { readJson, sendJson } from '$lib/components/api-client.js';
  import type {
    AccountView,
    CategoryView,
    TransactionPageView
  } from '$lib/components/phase1-types.js';
  import {
    initializeMarketScope,
    marketState,
    withMarket,
    type MarketSelection
  } from '$lib/market-scope.js';

  const DEFAULT_PAGE_SIZE = 25;
  const sorts: TransactionSort[] = ['booked_date_desc', 'booked_date_asc', 'amount_desc', 'amount_asc'];

  let accounts: AccountView[] = [];
  let categories: CategoryView[] = [];
  let data: TransactionPageView = { items: [], page: 1, pageSize: DEFAULT_PAGE_SIZE, total: 0, totalPages: 0 };
  let loading = true;
  let pageError = '';
  let savedMessage = '';
  let search = '';
  let accountId = '';
  let categoryId = '';
  let direction = '';
  let from = '';
  let to = '';
  let sort: TransactionSort = 'booked_date_desc';
  let page = 1;
  let pageSize = DEFAULT_PAGE_SIZE;
  let market: MarketSelection = '';

  $: hasFilters = Boolean(search || accountId || categoryId || direction || from || to || sort !== 'booked_date_desc' || pageSize !== DEFAULT_PAGE_SIZE);

  function readState(url: URL) {
    search = url.searchParams.get('search') ?? '';
    accountId = url.searchParams.get('accountId') ?? '';
    categoryId = url.searchParams.get('categoryId') ?? '';
    direction = url.searchParams.get('direction') ?? '';
    from = url.searchParams.get('from') ?? '';
    to = url.searchParams.get('to') ?? '';
    const nextSort = url.searchParams.get('sort') as TransactionSort | null;
    sort = nextSort && sorts.includes(nextSort) ? nextSort : 'booked_date_desc';
    page = Math.max(Number(url.searchParams.get('page')) || 1, 1);
    pageSize = Math.min(Math.max(Number(url.searchParams.get('pageSize')) || DEFAULT_PAGE_SIZE, 1), 100);
  }

  function queryString() {
    const query = new URLSearchParams();
    if (market) query.set('market', market);
    if (search) query.set('search', search);
    if (accountId) query.set('accountId', accountId);
    if (categoryId) query.set('categoryId', categoryId);
    if (direction) query.set('direction', direction);
    if (from) query.set('from', from);
    if (to) query.set('to', to);
    if (sort !== 'booked_date_desc') query.set('sort', sort);
    if (page > 1) query.set('page', String(page));
    if (pageSize !== DEFAULT_PAGE_SIZE) query.set('pageSize', String(pageSize));
    return query.toString();
  }

  async function syncUrl() {
    const query = queryString();
    await goto(query ? `/transactions?${query}` : '/transactions', {
      replaceState: true,
      noScroll: true,
      keepFocus: true
    });
  }

  async function loadReferences() {
    const [accountResult, categoryResult] = await Promise.all([
      readJson<AccountsResponse>(withMarket('/api/accounts', market)),
      readJson<CategoriesResponse>('/api/categories')
    ]);
    accounts = accountResult.accounts;
    categories = categoryResult.categories;
  }

  async function loadTransactions() {
    loading = true;
    pageError = '';
    try {
      const query = queryString();
      data = await readJson<TransactionPageView>(`/api/transactions${query ? `?${query}` : ''}`);
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Transactions are temporarily unavailable.';
      data = { items: [], page, pageSize, total: 0, totalPages: 0 };
    } finally {
      loading = false;
    }
  }

  async function applyFilters(filters: {
    search: string;
    accountId: string;
    categoryId: string;
    direction: string;
    from: string;
    to: string;
    sort: TransactionSort;
  }) {
    if (filters.from && filters.to && filters.from > filters.to) {
      pageError = 'The start date must be on or before the end date.';
      return;
    }
    search = filters.search.trim();
    accountId = filters.accountId;
    categoryId = filters.categoryId;
    direction = filters.direction;
    from = filters.from;
    to = filters.to;
    sort = filters.sort;
    page = 1;
    await syncUrl();
    await loadTransactions();
  }

  async function changePage(next: number) {
    page = Math.min(Math.max(Math.trunc(next), 1), Math.max(data.totalPages, 1));
    await syncUrl();
    await loadTransactions();
  }

  async function changePageSize(next: number) {
    pageSize = next;
    page = 1;
    await syncUrl();
    await loadTransactions();
  }

  async function saveCategory(transactionId: string, nextCategoryId: string, applyToMerchant: boolean) {
    const response = await sendJson<TransactionCategoryUpdateResponse>(`/api/transactions/${transactionId}`, 'PATCH', {
      categoryId: nextCategoryId,
      applyToMerchant
    });

    if (applyToMerchant) {
      savedMessage = `${response.merchantTransactionsUpdated.toLocaleString()} matching transactions updated.`;
      await loadTransactions();
      return;
    }

    data = {
      ...data,
      items: data.items.map((transaction) =>
        transaction.id === transactionId ? { ...transaction, ...response.transaction } : transaction
      )
    };
    savedMessage = 'Category saved for this transaction.';
  }

  async function initialize() {
    const marketResult = await initializeMarketScope(new URL(window.location.href));
    market = marketResult.market;
    readState(new URL(window.location.href));
    try {
      await loadReferences();
      if (accountId && !accounts.some((account) => account.id === accountId)) {
        accountId = '';
        page = 1;
        await syncUrl();
      }
      await loadTransactions();
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The ledger is temporarily unavailable.';
      loading = false;
    }
  }

  function handleHistory() {
    void (async () => {
      const state = await initializeMarketScope(new URL(window.location.href));
      market = state.market;
      readState(new URL(window.location.href));
      await loadReferences();
      if (accountId && !accounts.some((account) => account.id === accountId)) accountId = '';
      await loadTransactions();
    })();
  }

  function handleMarketChange(event: Event) {
    void (async () => {
      market = (event as CustomEvent<{ market: MarketSelection }>).detail.market;
      await loadReferences();
      if (accountId && !accounts.some((account) => account.id === accountId)) {
        accountId = '';
        page = 1;
        await syncUrl();
      }
      await loadTransactions();
    })();
  }

  onMount(() => {
    void initialize();
    window.addEventListener('popstate', handleHistory);
    window.addEventListener('ledger:market-change', handleMarketChange);
    return () => {
      window.removeEventListener('popstate', handleHistory);
      window.removeEventListener('ledger:market-change', handleMarketChange);
    };
  });
</script>

<svelte:head>
  <title>Transactions · Ledger</title>
  <meta name="description" content="Filter, inspect, and correct every transaction in your ledger." />
</svelte:head>

<div class="page">
  <header class="page-header">
    <div class="page-header-copy">
      <p class="eyebrow">Canonical ledger</p>
      <h1>Every transaction, traceable.</h1>
      <p class="lede">Filter the full record, inspect account-posted activity, and open reporting or conversion evidence only when you need it.</p>
    </div>
    {#if hasFilters}<a class="button-secondary" href={withMarket('/transactions', market)}>Clear filters</a>{/if}
  </header>

  {#if pageError}
    <div class="status-banner" role="alert">
      <strong>Transactions need attention.</strong>
      <span>{pageError}</span>
      <button class="button-secondary" type="button" on:click={loadTransactions}>Try again</button>
    </div>
  {:else if savedMessage}
    <div class="status-banner success" role="status">
      <strong>Saved.</strong><span>{savedMessage}</span>
      <button class="text-button" type="button" on:click={() => (savedMessage = '')}>Dismiss</button>
    </div>
  {/if}

  <TransactionsTable
    {data}
    {accounts}
    {categories}
    {loading}
    {search}
    {accountId}
    {categoryId}
    {direction}
    {from}
    {to}
    {sort}
    {market}
    reportingCurrency={$marketState.settings?.baseCurrency ?? data.items[0]?.currencyBase ?? 'CAD'}
    onFilter={applyFilters}
    onPage={changePage}
    onPageSize={changePageSize}
    onCategorySave={saveCategory}
  />
</div>
