<script lang="ts">
  import { marketState, withMarket } from '$lib/market-scope.js';
</script>

<svelte:head>
  <title>More · Ledger</title>
  <meta name="description" content="Manage accounts, categories, imports, and Ledger settings." />
</svelte:head>

<div class="page more-page">
  <header class="page-header">
    <div class="page-header-copy">
      <p class="eyebrow">Ledger tools</p>
      <h1>Everything else, close at hand.</h1>
      <p class="lede">Manage the parts of your ledger that support day-to-day activity and reporting.</p>
    </div>
  </header>

  <nav class="more-grid" aria-label="Ledger management">
    <a href={$marketState.ready ? withMarket('/accounts', $marketState.market) : '/accounts'}><span aria-hidden="true">▣</span><div><strong>Accounts</strong><small>Balances, markets, limits, and institutions</small></div><b aria-hidden="true">→</b></a>
    <a href="/categories"><span aria-hidden="true">◫</span><div><strong>Categories</strong><small>Rules, proposals, and merchant corrections</small></div><b aria-hidden="true">→</b></a>
    <a href={$marketState.ready ? withMarket('/imports', $marketState.market) : '/imports'}><span aria-hidden="true">↑</span><div><strong>Imports</strong><small>Statements and reconciliation history</small></div><b aria-hidden="true">→</b></a>
    <a href="/settings"><span aria-hidden="true">⚙</span><div><strong>Settings</strong><small>Market defaults, home currency, and advanced analytics</small></div><b aria-hidden="true">→</b></a>
  </nav>
</div>

<style>
  .more-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.8rem; }
  .more-grid a { display: grid; grid-template-columns: auto 1fr auto; min-height: 126px; padding: 1rem; align-items: center; gap: 0.9rem; color: inherit; border: 1px solid var(--line); border-radius: 17px; background: var(--paper); box-shadow: var(--shadow); text-decoration: none; }
  .more-grid a:hover { border-color: #aebbb6; transform: translateY(-1px); }
  .more-grid a > span { display: grid; width: 45px; height: 45px; place-items: center; color: var(--forest); border-radius: 13px; background: var(--mint); font-size: 1.15rem; font-weight: 850; }
  .more-grid div { display: grid; gap: 0.25rem; }
  .more-grid strong { color: var(--forest); font-size: 1rem; }
  .more-grid small { color: var(--muted); font-size: 0.67rem; line-height: 1.45; }
  .more-grid b { color: var(--forest); }
  @media (max-width: 650px) { .more-grid { grid-template-columns: 1fr; } .more-grid a { min-height: 104px; } }
</style>
