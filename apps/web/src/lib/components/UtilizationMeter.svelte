<script lang="ts">
  import { money } from '$lib/format.js';

  export let label = 'Credit utilization';
  export let value: string | null | undefined = null;
  export let used: string | null | undefined = null;
  export let limit: string | null | undefined = null;
  export let available: string | null | undefined = null;
  export let currency = 'CAD';
  export let compact = false;

  $: numericValue = value == null ? null : Number(value);
  $: width = numericValue == null || !Number.isFinite(numericValue) ? 0 : Math.min(Math.max(numericValue, 0), 100);
  $: tone = numericValue == null ? 'unknown' : numericValue >= 90 ? 'high' : numericValue >= 70 ? 'watch' : 'healthy';
</script>

<div class:compact class="utilization">
  <div class="topline">
    <span>{label}</span>
    <strong class:high={tone === 'high'}>
      {numericValue == null || !Number.isFinite(numericValue) ? 'Not available' : `${numericValue.toFixed(1)}%`}
    </strong>
  </div>
  <div
    class:high={tone === 'high'}
    class:watch={tone === 'watch'}
    class="track"
    role="meter"
    aria-label={label}
    aria-valuemin="0"
    aria-valuemax="100"
    aria-valuenow={numericValue == null || !Number.isFinite(numericValue) ? undefined : numericValue}
    aria-valuetext={numericValue == null || !Number.isFinite(numericValue) ? 'Not available' : `${numericValue.toFixed(1)} percent`}
  >
    <span style={`width: ${width}%`}></span>
  </div>
  {#if !compact}
    <div class="details">
      <span>{used == null ? 'Balance unavailable' : `${money(used, currency)} used`}</span>
      <span>{limit == null ? 'Add a credit limit' : `${money(limit, currency)} limit`}</span>
      {#if available != null}<span>{money(available, currency)} available</span>{/if}
    </div>
  {/if}
</div>

<style>
  .utilization { display: grid; gap: 0.45rem; }
  .topline,
  .details {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.7rem;
  }
  .topline span,
  .details { color: var(--muted); font-size: 0.64rem; font-weight: 650; }
  .topline strong { color: var(--forest); font-size: 0.75rem; }
  .topline strong.high { color: var(--danger); }
  .track { height: 7px; overflow: hidden; border-radius: 999px; background: #e5e7e1; }
  .track span { display: block; height: 100%; border-radius: inherit; background: var(--success); }
  .track.watch span { background: var(--gold); }
  .track.high span { background: var(--coral); }
  .details { justify-content: flex-start; flex-wrap: wrap; }
  .details span + span::before { margin-right: 0.7rem; color: #aab1ad; content: '·'; }
  .compact { gap: 0.32rem; }
  .compact .track { height: 5px; }
</style>
