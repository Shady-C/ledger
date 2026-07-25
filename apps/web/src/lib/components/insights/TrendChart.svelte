<script lang="ts">
  import type { InsightTrendPoint } from '@ledger/shared-types';

  import { money } from '$lib/format.js';

  export let points: InsightTrendPoint[] = [];
  export let currency = 'CAD';
  export let label = 'Monthly spending trend';

  const width = 720;
  const height = 250;
  const plotTop = 18;
  const plotBottom = 210;

  $: ordered = [...points].sort((left, right) => left.period.localeCompare(right.period));
  $: maximum = Math.max(1, ...ordered.map((point) => Math.abs(Number(point.spending)) || 0));
  $: slotWidth = ordered.length ? width / ordered.length : width;
  $: barWidth = Math.max(5, Math.min(36, slotWidth * 0.58));

  function barHeight(value: string) {
    return (Math.abs(Number(value)) / maximum) * (plotBottom - plotTop);
  }

  function periodLabel(value: string) {
    const date = new Date(`${value}T00:00:00Z`);
    return Number.isNaN(date.getTime())
      ? value
      : new Intl.DateTimeFormat(undefined, {
          month: 'short',
          year: '2-digit',
          timeZone: 'UTC'
        }).format(date);
  }
</script>

{#if ordered.length === 0}
  <div class="chart-empty" role="status">
    <strong>No trend data yet</strong>
    <span>Monthly spending will appear after an analytics refresh.</span>
  </div>
{:else}
  <div class="chart-shell">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="trend-title trend-description">
      <title id="trend-title">{label}</title>
      <desc id="trend-description">Monthly {currency} spending from {periodLabel(ordered[0]!.period)} to {periodLabel(ordered[ordered.length - 1]!.period)}.</desc>
      <line x1="0" x2={width} y1={plotBottom} y2={plotBottom} class="axis" />
      {#each ordered as point, index}
        {@const renderedHeight = barHeight(point.spending)}
        {@const x = index * slotWidth + (slotWidth - barWidth) / 2}
        <g>
          <rect
            {x}
            y={plotBottom - renderedHeight}
            width={barWidth}
            height={Math.max(1, renderedHeight)}
            rx="5"
            class:partial={point.coverageStatus === 'partial'}
          >
            <title>{periodLabel(point.period)}: {money(point.spending, currency)} spending{point.coverageStatus === 'partial' ? ' (partial)' : ''}</title>
          </rect>
          {#if ordered.length <= 12 || index % 2 === 0}
            <text x={index * slotWidth + slotWidth / 2} y="235" text-anchor="middle">{periodLabel(point.period)}</text>
          {/if}
        </g>
      {/each}
    </svg>
    <ul class="chart-values" aria-label="Trend values">
      {#each ordered as point}
        <li><span>{periodLabel(point.period)}</span><strong>{money(point.spending, currency)}</strong>{#if point.coverageStatus === 'partial'}<small>Partial</small>{/if}</li>
      {/each}
    </ul>
  </div>
{/if}

<style>
  .chart-shell { min-width: 0; }
  svg { display: block; width: 100%; min-height: 210px; overflow: visible; }
  .axis { stroke: #cfd4cd; stroke-width: 1; }
  rect { fill: var(--forest-mid); }
  rect.partial { fill: var(--gold); opacity: 0.78; }
  text { fill: var(--muted); font-size: 10px; font-weight: 650; }
  .chart-values {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
  .chart-empty {
    display: grid;
    min-height: 210px;
    padding: 1rem;
    place-content: center;
    justify-items: center;
    color: var(--muted);
    text-align: center;
  }
  .chart-empty strong { color: var(--ink); }
  .chart-empty span { margin-top: 0.35rem; font-size: 0.72rem; }
  @media (max-width: 620px) {
    svg { min-width: 580px; }
    .chart-shell { overflow-x: auto; padding-bottom: 0.35rem; }
  }
</style>
