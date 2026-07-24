<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import type { CashflowPoint } from '@ledger/shared-types';
  import type { EChartsType } from 'echarts/core';

  export let points: CashflowPoint[] = [];
  export let currency = 'CAD';
  export let loading = false;

  let host: HTMLDivElement;
  let chart: EChartsType | undefined;
  let chartInit: typeof import('echarts/core')['init'] | undefined;
  let observer: ResizeObserver | undefined;

  function render() {
    if (!host || !chartInit || points.length === 0) return;
    chart ??= chartInit(host, undefined, { renderer: 'canvas' });
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    chart.setOption(
      {
        animation: !reduced,
        aria: { enabled: true, decal: { show: true } },
        color: ['#75ad9f', '#e36f54'],
        grid: { left: 12, right: 12, top: 18, bottom: 24, containLabel: true },
        tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => `${currency} ${Number(value).toFixed(2)}` },
        legend: { bottom: 0, textStyle: { color: '#64706d', fontFamily: 'Manrope Variable' } },
        xAxis: {
          type: 'category',
          data: points.map((point) => point.period),
          axisTick: { show: false },
          axisLine: { lineStyle: { color: '#cfd4ce' } },
          axisLabel: {
            color: '#6e7a76',
            formatter: (value: string) => new Intl.DateTimeFormat(undefined, {
              month: 'short',
              year: '2-digit',
              timeZone: 'UTC'
            }).format(new Date(`${value}T00:00:00Z`))
          }
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: '#6e7a76', formatter: (value: number) => `${Math.round(value / 100) / 10}k` },
          splitLine: { lineStyle: { color: '#e7e7e0' } }
        },
        series: [
          {
            name: 'Inflow',
            type: 'bar',
            barMaxWidth: 24,
            itemStyle: { borderRadius: [5, 5, 0, 0] },
            data: points.map((point) => Number(point.inflow))
          },
          {
            name: 'Outflow',
            type: 'bar',
            barMaxWidth: 24,
            itemStyle: { borderRadius: [5, 5, 0, 0] },
            data: points.map((point) => Number(point.outflow))
          }
        ]
      },
      true
    );
  }

  $: if (chartInit && host && points) render();

  onMount(async () => {
    const [core, charts, components, renderers] = await Promise.all([
      import('echarts/core'),
      import('echarts/charts'),
      import('echarts/components'),
      import('echarts/renderers')
    ]);
    core.use([
      charts.BarChart,
      components.AriaComponent,
      components.GridComponent,
      components.LegendComponent,
      components.TooltipComponent,
      renderers.CanvasRenderer
    ]);
    chartInit = core.init;
    render();
    observer = new ResizeObserver(() => chart?.resize());
    observer.observe(host);
  });

  onDestroy(() => {
    observer?.disconnect();
    chart?.dispose();
  });
</script>

<div class="chart-shell">
  <div
    class:hidden={loading || points.length === 0}
    class="chart"
    bind:this={host}
    role="img"
    aria-label={`Cash-flow chart with ${points.length} monthly periods in ${currency}`}
  ></div>
  {#if loading}
    <div class="loading" aria-label="Loading cash flow" aria-busy="true"></div>
  {:else if points.length === 0}
    <div class="empty">
      <span aria-hidden="true">↕</span>
      <strong>No cash-flow periods yet</strong>
      <p>Imported statement activity will be summarized here month by month.</p>
    </div>
  {/if}
</div>

<style>
  .chart-shell,
  .chart {
    width: 100%;
    min-height: 260px;
  }

  .chart-shell { position: relative; }
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
    color: var(--forest);
    border-radius: 50%;
    background: var(--mint);
    font-size: 1.25rem;
  }

  .empty strong { color: var(--ink); }
  .empty p { max-width: 32ch; margin: 0.35rem 0 0; font-size: 0.78rem; }

  .loading {
    min-height: 260px;
    border-radius: 10px;
    background:
      linear-gradient(90deg, transparent 9%, #dfe4de 10% 14%, transparent 15% 29%, #efd8d0 30% 34%, transparent 35%) 0 100% / 25% 72% repeat-x,
      #f1f0ea;
    animation: pulse 1.4s ease-in-out infinite alternate;
  }

  @keyframes pulse { to { opacity: 0.55; } }
</style>
