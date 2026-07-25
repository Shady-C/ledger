<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import {
    initializeMarketScope,
    marketParams,
    marketState,
    setMarketScope,
    type MarketSelection
  } from '$lib/market-scope.js';

  const choices: { value: MarketSelection; label: string }[] = [
    { value: '', label: 'All' },
    { value: 'CA', label: 'Canada' },
    { value: 'TZ', label: 'Tanzania' }
  ];

  let changing = false;
  let mounted = false;

  $: if (mounted && $marketState.ready) {
    const urlMarket = $page.url.searchParams.get('market');
    const resolved = urlMarket === 'CA' || urlMarket === 'TZ'
      ? urlMarket
      : $page.url.searchParams.has('market') && (urlMarket === '' || urlMarket === 'ALL')
        ? ''
        : null;
    if (resolved !== null && resolved !== $marketState.market) {
      setMarketScope(resolved);
    }
  }

  async function select(market: MarketSelection) {
    if (changing || market === $marketState.market) return;
    changing = true;
    try {
      setMarketScope(market);
      const params = marketParams(market, $page.url.searchParams);
      const query = params.toString();
      await goto(`${$page.url.pathname}${query ? `?${query}` : ''}${$page.url.hash}`, {
        replaceState: true,
        noScroll: true,
        keepFocus: true
      });
    } finally {
      changing = false;
    }
  }

  onMount(() => {
    mounted = true;
    void initializeMarketScope(new URL(window.location.href));
    return () => { mounted = false; };
  });
</script>

<section class="scope-bar" aria-label="Market scope">
  <div>
    <span class="scope-label">View</span>
    <div class="segmented">
      {#each choices as choice}
        <button
          type="button"
          class:active={$marketState.ready && $marketState.market === choice.value}
          aria-pressed={$marketState.ready && $marketState.market === choice.value}
          disabled={changing || !$marketState.ready}
          on:click={() => select(choice.value)}
        >{choice.label}</button>
      {/each}
    </div>
  </div>
  <p>{!$marketState.ready ? 'Loading scope…' : $marketState.market ? `Showing ${$marketState.market === 'CA' ? 'Canadian' : 'Tanzanian'} accounts and activity.` : 'Showing the complete consolidated ledger.'}</p>
</section>

<style>
  .scope-bar {
    display: flex;
    width: min(var(--page-width), calc(100% - 2rem));
    min-height: 48px;
    margin: 0 auto;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }
  .scope-bar > div { display: flex; align-items: center; gap: 0.65rem; }
  .scope-label { color: var(--muted); font-size: 0.61rem; font-weight: 850; letter-spacing: 0.08em; text-transform: uppercase; }
  .segmented { display: flex; padding: 0.2rem; border: 1px solid var(--line); border-radius: 10px; background: rgb(252 251 247 / 70%); }
  button { min-height: 31px; padding: 0.35rem 0.7rem; color: var(--muted); border: 0; border-radius: 7px; background: transparent; font-size: 0.65rem; font-weight: 800; }
  button.active { color: white; background: var(--forest); }
  button:disabled:not(.active) { opacity: 0.5; }
  p { margin: 0; color: var(--muted); font-size: 0.61rem; }
  @media (max-width: 600px) {
    .scope-bar { width: min(100% - 1.2rem, var(--page-width)); min-height: 54px; }
    .scope-bar p, .scope-label { display: none; }
    .scope-bar > div, .segmented { width: 100%; }
    button { flex: 1; }
  }
</style>
