<script lang="ts">
  import { onMount } from 'svelte';
  import type {
    AccountsResponse,
    BalanceResponse,
    CashflowResponse,
    FxAnalyticsResponse,
    InsightSummaryResponse,
    NetWorthResponse
  } from '@ledger/shared-types';

  import AccountStrip from '$lib/components/AccountStrip.svelte';
  import RecentTransactions from '$lib/components/RecentTransactions.svelte';
  import UtilizationMeter from '$lib/components/UtilizationMeter.svelte';
  import { readJson, readOptionalJson } from '$lib/components/api-client.js';
  import type { AccountView, TransactionPageView } from '$lib/components/phase1-types.js';
  import BalanceChart from '$lib/charts/BalanceChart.svelte';
  import CashflowChart from '$lib/charts/CashflowChart.svelte';
  import { money } from '$lib/format.js';

  let accounts: AccountView[] = [];
  let balance: BalanceResponse = { currency: 'CAD', basis: 'net_activity', points: [] };
  let cashflow: CashflowResponse = { currency: 'CAD', points: [] };
  let transactions: TransactionPageView = { items: [], page: 1, pageSize: 6, total: 0, totalPages: 0 };
  let netWorth: NetWorthResponse | null = null;
  let fx: FxAnalyticsResponse | null = null;
  let insights: InsightSummaryResponse | null = null;
  let creditUtilization: AccountsResponse['creditUtilization'] | null = null;
  let selectedAccount = '';
  let loading = true;
  let pageError = '';

  $: cards = accounts.filter((account) => account.kind === 'credit_card');
  $: displayCurrency = netWorth?.baseCurrency ?? creditUtilization?.baseCurrency ?? balance.currency;
  $: assets = netWorth?.assets ?? null;
  $: liabilities = netWorth?.liabilities ?? null;
  $: worth = netWorth?.netWorth ?? null;
  $: latestCashflow = cashflow.points.at(-1);
  $: partial = netWorth?.status === 'partial';
  $: analyticsPartial = insights?.coverage.status === 'partial';

  type DashboardSnapshot = {
    accountResult: AccountsResponse;
    balanceResult: BalanceResponse;
    cashflowResult: CashflowResponse;
    transactionResult: TransactionPageView;
    worthResult: NetWorthResponse | null;
    fxResult: FxAnalyticsResponse | null;
    insightResult: InsightSummaryResponse | null;
  };

  function snapshotBaseCurrencies(snapshot: DashboardSnapshot) {
    return new Set([
      snapshot.accountResult.creditUtilization.baseCurrency,
      ...snapshot.accountResult.accounts.map((account) => account.baseCurrency),
      snapshot.balanceResult.currency,
      snapshot.cashflowResult.currency,
      ...(snapshot.worthResult ? [snapshot.worthResult.baseCurrency] : []),
      ...(snapshot.fxResult ? [snapshot.fxResult.baseCurrency] : []),
      ...(snapshot.insightResult ? [snapshot.insightResult.baseCurrency] : []),
      ...snapshot.transactionResult.items.map((transaction) => transaction.currencyBase)
    ]);
  }

  async function fetchDashboardSnapshot(attempt = 0): Promise<DashboardSnapshot> {
    const accountResult = await readJson<AccountsResponse>('/api/accounts');
    const analyticsSuffix = selectedAccount ? `?accountId=${encodeURIComponent(selectedAccount)}` : '';
    const insightSuffix = `?range=12m${selectedAccount ? `&accountId=${encodeURIComponent(selectedAccount)}` : ''}`;
    const [balanceResult, cashflowResult, transactionResult, worthResult, fxResult, insightResult] = await Promise.all([
      readJson<BalanceResponse>(`/api/analytics/balance${analyticsSuffix}`),
      readJson<CashflowResponse>(`/api/analytics/cashflow${analyticsSuffix}`),
      readJson<TransactionPageView>(`/api/transactions?pageSize=6${selectedAccount ? `&accountId=${encodeURIComponent(selectedAccount)}` : ''}`),
      readOptionalJson<NetWorthResponse>('/api/analytics/net-worth').catch(() => null),
      readOptionalJson<FxAnalyticsResponse>('/api/analytics/fx').catch(() => null),
      readOptionalJson<InsightSummaryResponse>(`/api/insights/summary${insightSuffix}`).catch(() => null)
    ]);
    const snapshot = { accountResult, balanceResult, cashflowResult, transactionResult, worthResult, fxResult, insightResult };

    if (snapshotBaseCurrencies(snapshot).size > 1) {
      if (attempt < 2) {
        await new Promise((resolve) => setTimeout(resolve, 75 * (attempt + 1)));
        return fetchDashboardSnapshot(attempt + 1);
      }
      throw new Error('Ledger valuation changed during this refresh. Try again to load one consistent base currency.');
    }
    return snapshot;
  }

  async function loadDashboard() {
    loading = true;
    pageError = '';
    try {
      const {
        accountResult,
        balanceResult,
        cashflowResult,
        transactionResult,
        worthResult,
        fxResult,
        insightResult
      } = await fetchDashboardSnapshot();
      accounts = accountResult.accounts;
      creditUtilization = accountResult.creditUtilization;
      balance = balanceResult;
      cashflow = cashflowResult;
      transactions = transactionResult;
      netWorth = worthResult;
      fx = fxResult;
      insights = insightResult;
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The dashboard is temporarily unavailable.';
    } finally {
      loading = false;
    }
  }

  async function selectAccount(accountId: string) {
    selectedAccount = accountId;
    await loadDashboard();
  }

  onMount(loadDashboard);
</script>

<svelte:head>
  <title>Dashboard · Ledger</title>
  <meta name="description" content="Your net worth, balances, card utilization, and recent ledger activity." />
</svelte:head>

<div class="page dashboard-page">
  <header class="page-header dashboard-header">
    <div class="page-header-copy">
      <p class="eyebrow">Financial overview</p>
      <h1>Know where you stand.</h1>
      <p class="lede">A current, traceable view of your assets, liabilities, spending, and available credit.</p>
    </div>
    <a class="button" href="/imports"><span aria-hidden="true">↑</span> Import statements</a>
  </header>

  {#if pageError}
    <div class="status-banner" role="alert">
      <strong>We couldn’t refresh everything.</strong>
      <span>{pageError}</span>
      <button class="button-secondary" type="button" on:click={loadDashboard}>Try again</button>
    </div>
  {/if}

  {#if partial}
    <div class="status-banner info" role="status">
      <strong>Net worth is partial.</strong>
      <span>
        {netWorth?.excludedAccounts.length ?? 0} {(netWorth?.excludedAccounts.length ?? 0) === 1 ? 'account is' : 'accounts are'} excluded until a verified balance and current exchange rate are available.
      </span>
      <a class="text-button" href="/accounts">Review accounts</a>
    </div>
  {/if}

  {#if analyticsPartial}
    <div class="status-banner info" role="status">
      <strong>Historical CAD analytics are partial.</strong>
      <span>{insights?.coverage.unvaluedTransactionCount ?? 0} transaction{(insights?.coverage.unvaluedTransactionCount ?? 0) === 1 ? '' : 's'} are excluded until a booked-date CAD rate is available.</span>
      <a class="text-button" href="/insights">Review coverage</a>
    </div>
  {/if}

  <section class="metrics" aria-label="Net worth summary">
    <article class="metric net-worth">
      <span>Net worth</span>
      <strong class:negative={worth?.startsWith('-')}>{loading || worth == null ? '—' : money(worth, displayCurrency)}</strong>
      <small>{netWorth ? `Valued ${netWorth.valuationDate}` : `${displayCurrency} current snapshot`}</small>
    </article>
    <article class="metric">
      <span>Assets</span>
      <strong>{loading || assets == null ? '—' : money(assets, displayCurrency)}</strong>
      <small>{accounts.filter((account) => account.kind !== 'credit_card').length} asset accounts</small>
    </article>
    <article class="metric liability">
      <span>Liabilities</span>
      <strong>{loading || liabilities == null ? '—' : money(liabilities, displayCurrency)}</strong>
      <small>{cards.length} credit {cards.length === 1 ? 'card' : 'cards'}</small>
    </article>
    <article class="metric">
      <span>FX costs</span>
      <strong>{loading || fx?.totalFxCostBase == null ? '—' : money(fx.totalFxCostBase, fx.baseCurrency)}</strong>
      <small>{fx ? `Actual fees ${money(fx.totalExplicitFeeBase, fx.baseCurrency)} · estimated markup ${money(fx.totalEstimatedMarkupBase, fx.baseCurrency)}` : 'Actual fees and estimated markup are reported separately'}</small>
    </article>
  </section>

  {#if fx && fx.transactions.length > 0}
    <details class="fx-breakdown panel">
      <summary>
        <span>
          <strong>FX rate and cost evidence</strong>
          <small>Statement fees are actual. Market-rate markup is an estimate.</small>
        </span>
        <span>{fx.missingRateCount > 0 ? `${fx.missingRateCount} rate${fx.missingRateCount === 1 ? '' : 's'} pending` : 'All rates available'}</span>
      </summary>
      <div class="fx-evidence-list">
        {#each fx.transactions.slice(0, 5) as transaction}
          <article>
            <div>
              <strong>{transaction.description}</strong>
              <small>{transaction.accountName} · {transaction.bookedDate}</small>
            </div>
            <dl>
              {#if transaction.foreignCurrency && transaction.bankAppliedRate}
                <div><dt>Bank-applied rate</dt><dd>1 {transaction.foreignCurrency} = {transaction.bankAppliedRate} {transaction.nativeCurrency}</dd></div>
              {/if}
              {#if transaction.foreignCurrency && transaction.marketRate}
                <div><dt>Reference market rate</dt><dd>1 {transaction.foreignCurrency} = {transaction.marketRate} {transaction.nativeCurrency}{transaction.marketRateDate ? ` · ${transaction.marketRateDate}` : ''}</dd></div>
              {:else if transaction.foreignCurrency || transaction.explicitFeeBase == null}
                <div><dt>Reference market rate</dt><dd>Pending</dd></div>
              {/if}
              {#if transaction.explicitFeeNative !== '0'}
                <div><dt>Actual statement fee</dt><dd>{money(transaction.explicitFeeNative, transaction.nativeCurrency)}{transaction.explicitFeeBase ? ` · ${money(transaction.explicitFeeBase, fx.baseCurrency)}` : ' · CAD pending'}</dd></div>
              {/if}
              {#if transaction.estimatedMarkupNative != null}
                <div><dt>Estimated markup</dt><dd>{transaction.markupPercent ?? '0'}% · {money(transaction.estimatedMarkupNative, transaction.nativeCurrency)}{transaction.estimatedMarkupBase ? ` · ${money(transaction.estimatedMarkupBase, fx.baseCurrency)}` : ' · CAD pending'}</dd></div>
              {/if}
            </dl>
          </article>
        {/each}
      </div>
      {#if fx.transactions.length > 5}<p class="fx-more">Showing 5 of {fx.transactions.length} FX-related records.</p>{/if}
    </details>
  {/if}

  <a class="insights-summary panel" href="/insights" aria-label={`Open Insights${insights?.findings.unread ? `, ${insights.findings.unread} unread findings` : ''}`}>
    <div>
      <span class="eyebrow">Insights</span>
      <strong>{insights ? `${insights.recurring.activeSeries} recurring patterns` : 'Explore ledger patterns'}</strong>
      <small>{insights?.coverage.status === 'partial' ? `${insights.coverage.unvaluedTransactionCount} transactions await CAD valuation.` : 'Trends, seasonality, recurring activity, and explainable findings.'}</small>
    </div>
    <span class="insight-action">
      {#if insights?.findings.unread}
        <span class="unread-badge">{insights.findings.unread} new</span>
      {/if}
      Review insights <span aria-hidden="true">→</span>
    </span>
  </a>

  <AccountStrip {accounts} {loading} selected={selectedAccount} onSelect={selectAccount} />

  <section class="credit-panel panel" aria-labelledby="credit-heading">
    <div class="panel-heading">
      <div>
        <h2 id="credit-heading">Credit utilization</h2>
        <p>Card balances compared with their native-currency limits.</p>
      </div>
      <a class="text-button" href="/accounts">Manage limits <span aria-hidden="true">→</span></a>
    </div>

    {#if loading}
      <div class="skeleton-block" aria-label="Loading credit utilization" aria-busy="true"></div>
    {:else if cards.length === 0}
      <div class="empty-state">
        <strong>No credit cards yet</strong>
        <p>Add a credit-card account to track available credit and utilization.</p>
      </div>
    {:else}
      <div class="credit-grid">
        <article class="aggregate">
          <span>Across cards with limits</span>
          <strong>{creditUtilization?.utilizationPercent == null ? '—' : `${creditUtilization.utilizationPercent}%`}</strong>
          <UtilizationMeter
            label="Aggregate credit utilization"
            value={creditUtilization?.utilizationPercent}
            used={creditUtilization?.usedCreditBase}
            limit={creditUtilization?.creditLimitBase}
            available={creditUtilization?.availableCreditBase}
            currency={creditUtilization?.baseCurrency ?? displayCurrency}
          />
          {#if creditUtilization?.excludedAccounts.length}
            <small>{creditUtilization.excludedAccounts.length} {creditUtilization.excludedAccounts.length === 1 ? 'card excluded' : 'cards excluded'} from the aggregate.</small>
          {/if}
        </article>
        {#each cards as card}
          <article class="card-utilization">
            <div>
              <span>{card.institutionName ?? 'Credit card'}</span>
              <strong>{card.displayName}</strong>
            </div>
            <UtilizationMeter
              label={`${card.displayName} utilization`}
              value={card.utilizationPercent}
              used={card.usedCredit}
              limit={card.creditLimit}
              available={card.availableCredit}
              currency={card.nativeCurrency}
            />
          </article>
        {/each}
      </div>
    {/if}
  </section>

  <section class="charts" aria-label="Ledger analytics">
    <article class="panel chart-card balance-card">
      <div class="panel-heading">
        <div>
          <h2>{balance.basis === 'net_activity' ? 'Cumulative net activity' : 'Daily position'}</h2>
          <p>{selectedAccount ? 'Selected-account balance history.' : 'Consolidated balance history.'}</p>
        </div>
        <span class="pill">{balance.currency}</span>
      </div>
      <BalanceChart
        points={balance.points}
        currency={balance.currency}
        {loading}
        label={balance.basis === 'net_activity' ? 'Cumulative net activity' : 'Running balance'}
      />
    </article>

    <article class="panel chart-card">
      <div class="panel-heading">
        <div>
          <h2>Cash flow</h2>
          <p>{latestCashflow ? `Latest net ${money(latestCashflow.net, cashflow.currency)}. Card payments shown separately.` : 'Monthly inflows, outflows, and card payments.'}</p>
        </div>
        <span class="pill">{cashflow.currency}</span>
      </div>
      <CashflowChart points={cashflow.points} currency={cashflow.currency} {loading} />
    </article>
  </section>

  <RecentTransactions transactions={transactions.items} {loading} />
</div>

<style>
  .dashboard-page { gap: clamp(1rem, 2.4vw, 1.7rem); }
  .dashboard-header { padding-bottom: 0.5rem; }
  .dashboard-header h1 { font-size: clamp(2.65rem, 6vw, 5.2rem); }
  .metrics { display: grid; grid-template-columns: 1.35fr repeat(3, 1fr); gap: 0.75rem; }
  .metric {
    display: grid;
    min-width: 0;
    min-height: 132px;
    padding: 1rem;
    align-content: space-between;
    gap: 0.7rem;
    border: 1px solid var(--line);
    border-radius: 16px;
    background: rgb(252 251 247 / 82%);
  }
  .metric.net-worth { color: white; border-color: var(--forest); background: var(--forest); box-shadow: var(--shadow); }
  .metric > span { color: var(--muted); font-size: 0.67rem; font-weight: 750; }
  .metric.net-worth > span,
  .metric.net-worth small { color: #bcd0ca; }
  .metric strong { overflow: hidden; color: var(--forest); font-size: clamp(1.25rem, 2.3vw, 1.85rem); letter-spacing: -0.05em; text-overflow: ellipsis; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .metric.net-worth strong { color: white; }
  .metric strong.negative,
  .metric.liability strong { color: var(--coral); }
  .metric small { color: var(--muted); font-size: 0.62rem; }
  .fx-breakdown { padding: 0; overflow: clip; }
  .fx-breakdown summary { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1rem 1.15rem; cursor: pointer; list-style-position: inside; }
  .fx-breakdown summary > span:first-child { display: inline-grid; gap: 0.2rem; margin-left: 0.35rem; }
  .fx-breakdown summary small,
  .fx-breakdown summary > span:last-child,
  .fx-evidence-list small,
  .fx-more { color: var(--muted); font-size: 0.64rem; }
  .fx-evidence-list { display: grid; border-top: 1px solid var(--line); }
  .fx-evidence-list article { display: grid; grid-template-columns: minmax(180px, 0.7fr) minmax(0, 1.3fr); gap: 1rem; padding: 0.9rem 1.15rem; border-bottom: 1px solid var(--line); }
  .fx-evidence-list article > div { display: grid; align-content: start; gap: 0.2rem; }
  .fx-evidence-list dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.55rem 1rem; margin: 0; }
  .fx-evidence-list dl div { min-width: 0; }
  .fx-evidence-list dt { color: var(--muted); font-size: 0.58rem; font-weight: 750; text-transform: uppercase; }
  .fx-evidence-list dd { margin: 0.16rem 0 0; overflow-wrap: anywhere; font-size: 0.68rem; font-variant-numeric: tabular-nums; }
  .fx-more { margin: 0; padding: 0.8rem 1.15rem; }
  .insights-summary { display: flex; align-items: center; justify-content: space-between; gap: 1rem; color: inherit; text-decoration: none; }
  .insights-summary > div { display: grid; gap: 0.22rem; }
  .insights-summary strong { font-size: 1rem; }
  .insights-summary small { color: var(--muted); font-size: 0.66rem; }
  .insight-action { display: flex; align-items: center; gap: 0.55rem; color: var(--forest); font-size: 0.7rem; font-weight: 800; white-space: nowrap; }
  .unread-badge { padding: 0.25rem 0.45rem; color: white; border-radius: 999px; background: var(--coral); font-size: 0.58rem; }
  .credit-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.7rem; }
  .aggregate,
  .card-utilization { display: grid; min-height: 150px; padding: 1rem; align-content: space-between; gap: 1rem; border: 1px solid #e3e4de; border-radius: 14px; background: #f8f7f2; }
  .aggregate { color: white; border-color: var(--forest-mid); background: var(--forest-mid); }
  .aggregate > span,
  .card-utilization > div span { color: var(--muted); font-size: 0.64rem; font-weight: 700; }
  .aggregate > span { color: #bcd0ca; }
  .aggregate > strong { font-size: 2rem; letter-spacing: -0.05em; }
  .aggregate :global(.topline span),
  .aggregate :global(.details),
  .aggregate > small { color: #bcd0ca; }
  .aggregate :global(.topline strong) { color: white; }
  .aggregate > small { font-size: 0.6rem; line-height: 1.4; }
  .card-utilization > div { display: grid; gap: 0.2rem; }
  .card-utilization > div strong { font-size: 0.84rem; }
  .charts { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.85fr); gap: 1rem; }
  .chart-card { min-width: 0; }
  @media (max-width: 980px) {
    .metrics { grid-template-columns: repeat(2, 1fr); }
    .credit-grid { grid-template-columns: repeat(2, 1fr); }
    .charts { grid-template-columns: 1fr; }
    .fx-evidence-list article { grid-template-columns: 1fr; }
  }
  @media (max-width: 620px) {
    .metrics,
    .credit-grid { grid-template-columns: 1fr; }
    .metric { min-height: 112px; }
    .dashboard-header .button { width: 100%; }
    .insights-summary { align-items: flex-start; flex-direction: column; }
    .fx-breakdown summary { align-items: flex-start; flex-direction: column; }
    .fx-evidence-list dl { grid-template-columns: 1fr; }
  }
</style>
