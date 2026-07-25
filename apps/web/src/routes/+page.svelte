<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import type { AccountsResponse, NetWorthResponse } from '@ledger/shared-types';
  import AccountStrip from '$lib/components/AccountStrip.svelte';
  import RecentTransactions from '$lib/components/RecentTransactions.svelte';
  import { readJson, readOptionalJson } from '$lib/components/api-client.js';
  import type { AccountView, TransactionPageView } from '$lib/components/phase1-types.js';
  import { money } from '$lib/format.js';
  import {
    initializeMarketScope,
    marketLabel,
    withMarket,
    type MarketSelection
  } from '$lib/market-scope.js';

  let accounts: AccountView[] = [];
  let transactions: TransactionPageView = { items: [], page: 1, pageSize: 6, total: 0, totalPages: 0 };
  let netWorth: NetWorthResponse | null = null;
  let market: MarketSelection = '';
  let loading = true;
  let pageError = '';

  $: displayCurrency = netWorth?.baseCurrency ?? accounts[0]?.baseCurrency ?? 'CAD';
  $: assets = netWorth?.assets ?? null;
  $: liabilities = netWorth?.liabilities ?? null;
  $: worth = netWorth?.netWorth ?? null;
  $: partial = netWorth?.status === 'partial';

  async function loadDashboard() {
    loading = true;
    pageError = '';
    try {
      const [accountResult, transactionResult, worthResult] = await Promise.all([
        readJson<AccountsResponse>(withMarket('/api/accounts', market)),
        readJson<TransactionPageView>(withMarket('/api/transactions?pageSize=6', market)),
        readOptionalJson<NetWorthResponse>(withMarket('/api/analytics/net-worth', market)).catch(() => null)
      ]);
      accounts = accountResult.accounts;
      transactions = transactionResult;
      netWorth = worthResult;
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The dashboard is temporarily unavailable.';
    } finally {
      loading = false;
    }
  }

  async function initialize() {
    const state = await initializeMarketScope(new URL(window.location.href));
    market = state.market;
    await loadDashboard();
  }

  function handleMarketChange(event: Event) {
    market = (event as CustomEvent<{ market: MarketSelection }>).detail.market;
    void loadDashboard();
  }

  function openAccount(accountId: string) {
    if (!accountId) return;
    void goto(withMarket(`/transactions?accountId=${encodeURIComponent(accountId)}`, market));
  }

  onMount(() => {
    void initialize();
    window.addEventListener('ledger:market-change', handleMarketChange);
    return () => window.removeEventListener('ledger:market-change', handleMarketChange);
  });
</script>

<svelte:head>
  <title>Home · Ledger</title>
  <meta name="description" content="Your scoped net worth, accounts, and recent ledger activity." />
</svelte:head>

<div class="page dashboard-page">
  <header class="page-header dashboard-header">
    <div class="page-header-copy">
      <p class="eyebrow">{marketLabel(market)} overview</p>
      <h1>Know where you stand.</h1>
      <p class="lede">A calm view of net worth, account balances, and recent activity. Conversion evidence stays one tap away.</p>
    </div>
    <a class="button" href={withMarket('/imports', market)}><span aria-hidden="true">↑</span> Import statements</a>
  </header>

  {#if pageError}
    <div class="status-banner" role="alert"><strong>We couldn’t refresh everything.</strong><span>{pageError}</span><button class="button-secondary" type="button" on:click={loadDashboard}>Try again</button></div>
  {/if}

  {#if partial}
    <div class="status-banner info" role="status">
      <strong>Net worth is partial.</strong>
      <span>{netWorth?.excludedAccounts.length ?? 0} {(netWorth?.excludedAccounts.length ?? 0) === 1 ? 'account is' : 'accounts are'} excluded until a verified balance and current exchange rate are available.</span>
      <a class="text-button" href={withMarket('/accounts', market)}>Review accounts</a>
    </div>
  {/if}

  <section class="metrics" aria-label="Net worth summary">
    <article class="metric net-worth"><span>Net worth</span><strong class:negative={worth?.startsWith('-')}>{loading || worth == null ? '—' : money(worth, displayCurrency)}</strong><small>{netWorth ? `${displayCurrency} · valued ${netWorth.valuationDate}` : `${displayCurrency} reporting snapshot`}</small></article>
    <article class="metric"><span>Assets</span><strong>{loading || assets == null ? '—' : money(assets, displayCurrency)}</strong><small>Consolidated reporting value</small></article>
    <article class="metric liability"><span>Liabilities</span><strong>{loading || liabilities == null ? '—' : money(liabilities, displayCurrency)}</strong><small>Consolidated reporting value</small></article>
  </section>

  <AccountStrip {accounts} {loading} showAll={false} onSelect={openAccount} />

  <RecentTransactions transactions={transactions.items} {loading} viewAllHref={withMarket('/transactions', market)} />
</div>

<style>
  .dashboard-page { gap: clamp(1rem, 2.4vw, 1.7rem); }
  .dashboard-header { padding-bottom: 0.5rem; }
  .dashboard-header h1 { font-size: clamp(2.65rem, 6vw, 5.2rem); }
  .metrics { display: grid; grid-template-columns: 1.35fr repeat(2, 1fr); gap: 0.75rem; }
  .metric { display: grid; min-width: 0; min-height: 132px; padding: 1rem; align-content: space-between; gap: 0.7rem; border: 1px solid var(--line); border-radius: 16px; background: rgb(252 251 247 / 82%); }
  .metric.net-worth { color: white; border-color: var(--forest); background: var(--forest); box-shadow: var(--shadow); }
  .metric > span { color: var(--muted); font-size: 0.67rem; font-weight: 750; }
  .metric.net-worth > span, .metric.net-worth small { color: #bcd0ca; }
  .metric strong { overflow: hidden; color: var(--forest); font-size: clamp(1.25rem, 2.3vw, 1.85rem); letter-spacing: -0.05em; text-overflow: ellipsis; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .metric.net-worth strong { color: white; }
  .metric strong.negative, .metric.liability strong { color: var(--coral); }
  .metric small { color: var(--muted); font-size: 0.62rem; }
  @media (max-width: 760px) { .metrics { grid-template-columns: 1fr; } .metric { min-height: 112px; } .dashboard-header .button { width: 100%; } }
</style>
