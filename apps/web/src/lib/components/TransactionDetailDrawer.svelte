<script lang="ts">
  import { onMount } from 'svelte';
  import type { TransactionDetailResponse } from '@ledger/shared-types';
  import { money, shortDate } from '$lib/format.js';
  import { withMarket, type MarketSelection } from '$lib/market-scope.js';
  import { readJson } from './api-client.js';

  export let transactionId: string;
  export let market: MarketSelection = '';
  export let onClose: () => void = () => undefined;

  let detail: TransactionDetailResponse | null = null;
  let loading = true;
  let error = '';
  let closeButton: HTMLButtonElement;

  async function load() {
    loading = true;
    error = '';
    try {
      detail = await readJson<TransactionDetailResponse>(
        withMarket(`/api/transactions/${transactionId}`, market)
      );
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'Conversion details are temporarily unavailable.';
    } finally {
      loading = false;
    }
  }

  function keydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
    }
    if (event.key === 'Tab') {
      const panel = document.getElementById('transaction-detail-panel');
      const focusable = panel?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), [tabindex="0"]');
      if (!focusable?.length) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }

  onMount(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButton?.focus();
    void load();
    return () => { document.body.style.overflow = previousOverflow; };
  });
</script>

<svelte:window on:keydown={keydown} />

<div class="backdrop" role="presentation" on:click={(event) => { if (event.target === event.currentTarget) onClose(); }}>
  <div id="transaction-detail-panel" class="drawer" role="dialog" aria-modal="true" aria-labelledby="transaction-detail-title" aria-describedby="transaction-detail-description">
    <header>
      <div>
        <p>Transaction audit</p>
        <h2 id="transaction-detail-title">Conversion details</h2>
      </div>
      <button bind:this={closeButton} type="button" aria-label="Close conversion details" on:click={onClose}>×</button>
    </header>

    {#if loading}
      <div class="drawer-loading" aria-busy="true" aria-label="Loading conversion details"><span></span><span></span><span></span></div>
    {:else if error}
      <div class="drawer-error" role="alert"><strong>Details need attention.</strong><p>{error}</p><button class="button-secondary" type="button" on:click={load}>Try again</button></div>
    {:else if detail}
      <p id="transaction-detail-description" class="summary">Audit evidence for {detail.transaction.merchantName ?? detail.transaction.description}, posted {shortDate(detail.transaction.postedDate ?? detail.transaction.bookedDate)}.</p>

      <div class="indicator-row" aria-label="Conversion status">
        {#each detail.conversionEvidence.indicators as indicator}
          <span class:pending={indicator === 'pending'}>{indicator === 'fx' ? 'FX' : indicator === 'converted' ? 'Converted' : 'Pending'}</span>
        {/each}
        {#if detail.conversionEvidence.indicators.length === 0}<span>Native</span>{/if}
      </div>

      <section aria-labelledby="money-layers-title">
        <h3 id="money-layers-title">Money layers</h3>
        <dl class="amounts">
          {#if detail.transaction.originalAmount != null && detail.transaction.originalCurrency}
            <div><dt>Original purchase</dt><dd>{money(detail.transaction.originalAmount, detail.transaction.originalCurrency)}</dd></div>
          {/if}
          <div><dt>Account-posted</dt><dd>{money(detail.transaction.amountNative, detail.transaction.currencyNative)}</dd></div>
          <div><dt>Reporting value</dt><dd>{detail.transaction.amountBase == null ? `${detail.transaction.currencyBase} valuation pending` : money(detail.transaction.amountBase, detail.transaction.currencyBase)}</dd></div>
        </dl>
      </section>

      <section aria-labelledby="rate-title">
        <h3 id="rate-title">Rates and costs</h3>
        <dl>
          <div><dt>Reporting rate</dt><dd>{detail.conversionEvidence.reportingRate ?? 'Not available'}{detail.conversionEvidence.reportingRateDate ? ` · ${shortDate(detail.conversionEvidence.reportingRateDate)}` : ''}</dd></div>
          <div><dt>Bank-applied rate</dt><dd>{detail.conversionEvidence.bankAppliedRate ?? 'Not supplied'}</dd></div>
          <div><dt>Reference rate</dt><dd>{detail.conversionEvidence.referenceRate ?? 'Not available'}{detail.conversionEvidence.referenceRateDate ? ` · ${shortDate(detail.conversionEvidence.referenceRateDate)}` : ''}{detail.conversionEvidence.referenceRateSource ? ` · ${detail.conversionEvidence.referenceRateSource}` : ''}</dd></div>
          <div><dt>Actual FX fee</dt><dd>{detail.conversionEvidence.explicitFeeNative == null ? 'None supplied' : money(detail.conversionEvidence.explicitFeeNative, detail.transaction.currencyNative)}{detail.conversionEvidence.explicitFeeBase != null ? ` · ${money(detail.conversionEvidence.explicitFeeBase, detail.transaction.currencyBase)} reporting` : ''}</dd></div>
          <div><dt>Estimated markup</dt><dd>{detail.conversionEvidence.estimatedMarkupNative == null ? 'Not available' : money(detail.conversionEvidence.estimatedMarkupNative, detail.transaction.currencyNative)}{detail.conversionEvidence.estimatedMarkupBase != null ? ` · ${money(detail.conversionEvidence.estimatedMarkupBase, detail.transaction.currencyBase)} reporting` : ''}</dd></div>
        </dl>
        <p class="caveat">Statement fees are actual. Reference-rate markup is an estimate.</p>
      </section>

      <section aria-labelledby="balance-title">
        <h3 id="balance-title">Balance after posting</h3>
        <dl>
          <div><dt>Native balance</dt><dd>{money(detail.conversionEvidence.runningBalanceNative, detail.transaction.currencyNative)}</dd></div>
          <div><dt>Reporting balance</dt><dd>{detail.conversionEvidence.runningBalanceBase == null ? 'Valuation pending' : money(detail.conversionEvidence.runningBalanceBase, detail.transaction.currencyBase)}</dd></div>
        </dl>
      </section>
    {/if}
  </div>
</div>

<style>
  .backdrop { position: fixed; z-index: 80; inset: 0; display: flex; justify-content: flex-end; background: rgb(10 28 27 / 44%); backdrop-filter: blur(3px); }
  .drawer { width: min(470px, 100%); height: 100%; padding: clamp(1rem, 3vw, 1.5rem); overflow-y: auto; color: var(--ink); background: var(--paper); box-shadow: -20px 0 60px rgb(8 30 28 / 22%); }
  header { display: flex; align-items: start; justify-content: space-between; gap: 1rem; padding-bottom: 1rem; border-bottom: 1px solid var(--line); }
  header p, header h2 { margin: 0; }
  header p { color: var(--coral); font-size: 0.61rem; font-weight: 850; letter-spacing: 0.1em; text-transform: uppercase; }
  header h2 { margin-top: 0.2rem; font-size: 1.5rem; letter-spacing: -0.04em; }
  header button { display: grid; width: 38px; height: 38px; place-items: center; color: var(--forest); border: 1px solid var(--line); border-radius: 10px; background: white; font-size: 1.35rem; }
  .summary { margin: 1rem 0; color: var(--muted); font-size: 0.7rem; line-height: 1.55; }
  .indicator-row { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 1rem; }
  .indicator-row span { padding: 0.28rem 0.52rem; color: #285049; border-radius: 999px; background: #e2f1ec; font-size: 0.59rem; font-weight: 850; }
  .indicator-row span.pending { color: #765c19; background: #f5e8bd; }
  section { padding: 1rem 0; border-top: 1px solid var(--line); }
  section h3 { margin: 0 0 0.7rem; font-size: 0.8rem; }
  dl { margin: 0; }
  dl div { display: grid; grid-template-columns: minmax(120px, 0.7fr) minmax(0, 1.3fr); gap: 1rem; padding: 0.52rem 0; border-top: 1px solid #e8e9e3; }
  dl div:first-child { border-top: 0; }
  dt { color: var(--muted); font-size: 0.62rem; }
  dd { margin: 0; overflow-wrap: anywhere; font-size: 0.67rem; font-weight: 750; text-align: right; font-variant-numeric: tabular-nums; }
  .amounts dd { color: var(--forest); font-size: 0.8rem; }
  .caveat { margin: 0.6rem 0 0; color: var(--muted); font-size: 0.58rem; line-height: 1.5; }
  .drawer-loading { display: grid; gap: 0.7rem; padding-top: 1.2rem; }
  .drawer-loading span { height: 100px; border-radius: 13px; background: #ecece6; animation: pulse 1s ease-in-out infinite alternate; }
  .drawer-error { margin-top: 1rem; padding: 1rem; border-radius: 12px; background: #fff0e9; }
  .drawer-error p { color: var(--muted); font-size: 0.68rem; }
  @keyframes pulse { to { opacity: 0.48; } }
  @media (max-width: 620px) {
    .backdrop { align-items: stretch; }
    .drawer { width: 100%; max-width: none; }
  }
</style>
