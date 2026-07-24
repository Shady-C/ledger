<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import type { BalancePoint } from '@ledger/shared-types';
  import type UPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';

  import { money } from '$lib/format.js';

  export let points: BalancePoint[] = [];
  export let currency = 'CAD';
  export let loading = false;

  let host: HTMLDivElement;
  let chart: UPlot | undefined;
  let UPlotClass: typeof UPlot | undefined;
  let observer: ResizeObserver | undefined;

  function render() {
    if (!host || !UPlotClass || points.length === 0) return;
    chart?.destroy();
    const width = Math.max(host.clientWidth, 260);
    const timestamps = points.map((point) => Date.parse(`${point.date}T00:00:00Z`) / 1000);
    const values = points.map((point) => Number(point.balance));
    chart = new UPlotClass(
      {
        width,
        height: 260,
        cursor: { drag: { x: true, y: false } },
        legend: { show: false },
        scales: { x: { time: true }, y: { auto: true } },
        axes: [
          { stroke: '#6e7a76', grid: { show: false }, ticks: { stroke: '#cfd4ce' }, size: 42 },
          {
            stroke: '#6e7a76',
            grid: { stroke: '#e7e7e0', width: 1 },
            ticks: { show: false },
            size: 68,
            values: (_u, ticks) => ticks.map((value) => money(value, currency).replace(/\.00$/, ''))
          }
        ],
        series: [
          {},
          {
            label: 'Balance',
            stroke: '#e36f54',
            width: 2.5,
            fill: 'rgba(227, 111, 84, 0.10)',
            points: { show: false }
          }
        ]
      },
      [timestamps, values],
      host
    );
  }

  $: if (UPlotClass && host && points) render();

  onMount(async () => {
    UPlotClass = (await import('uplot')).default;
    render();
    observer = new ResizeObserver(() => {
      if (chart && host.clientWidth > 0) chart.setSize({ width: host.clientWidth, height: 260 });
    });
    observer.observe(host);
  });

  onDestroy(() => {
    observer?.disconnect();
    chart?.destroy();
  });
</script>

<div class="chart-shell" class:waiting={loading}>
  <div
    class:hidden={loading || points.length === 0}
    class="chart"
    bind:this={host}
    role="img"
    aria-label={`Running balance chart with ${points.length} daily points in ${currency}`}
  ></div>
  {#if loading}
    <div class="loading" aria-label="Loading running balance" aria-busy="true"></div>
  {:else if points.length === 0}
    <div class="empty">
      <span aria-hidden="true">⌁</span>
      <strong>No balance history yet</strong>
      <p>Import a statement to draw your first running-balance line.</p>
    </div>
  {/if}
</div>

<style>
  .chart-shell {
    position: relative;
    min-height: 260px;
  }

  .chart {
    width: 100%;
    min-height: 260px;
  }

  .chart.hidden {
    position: absolute;
    visibility: hidden;
    pointer-events: none;
  }

  .empty {
    display: grid;
    min-height: 260px;
    place-content: center;
    justify-items: center;
    padding: 1rem;
    color: var(--muted);
    text-align: center;
  }

  .empty span {
    display: grid;
    width: 44px;
    height: 44px;
    margin-bottom: 0.8rem;
    place-items: center;
    color: var(--coral);
    border-radius: 50%;
    background: var(--coral-soft);
    font-size: 1.5rem;
  }

  .empty strong { color: var(--ink); }
  .empty p { max-width: 32ch; margin: 0.35rem 0 0; font-size: 0.78rem; }

  .loading {
    min-height: 260px;
    border-radius: 10px;
    background:
      linear-gradient(transparent 49%, #e6e7e0 50%, transparent 51%) 0 0 / 100% 25%,
      linear-gradient(100deg, transparent 20%, rgb(255 255 255 / 65%) 45%, transparent 70%) 0 0 / 200% 100%,
      #f1f0ea;
    animation: shimmer 1.5s infinite;
  }

  :global(.uplot) {
    font-family: inherit;
  }

  @keyframes shimmer { to { background-position: 0 0, -200% 0, 0 0; } }
</style>
