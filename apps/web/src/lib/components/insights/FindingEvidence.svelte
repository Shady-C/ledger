<script lang="ts">
  export let evidence: Record<string, unknown> = {};

  $: entries = Object.entries(evidence).sort(([left], [right]) => left.localeCompare(right));

  function label(value: string) {
    return value
      .replaceAll('_', ' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/^./, (character) => character.toUpperCase());
  }

  function display(value: unknown) {
    if (value === null || value === undefined) return 'Not available';
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'string' || typeof value === 'number') return String(value);
    return JSON.stringify(value, null, 2);
  }
</script>

{#if entries.length === 0}
  <p class="empty">No additional calculation evidence was stored.</p>
{:else}
  <dl>
    {#each entries as [key, value]}
      <div>
        <dt>{label(key)}</dt>
        <dd class:structured={typeof value === 'object' && value !== null}>{display(value)}</dd>
      </div>
    {/each}
  </dl>
{/if}

<style>
  dl { display: grid; gap: 0; margin: 0; }
  dl > div {
    display: grid;
    grid-template-columns: minmax(120px, 0.45fr) minmax(0, 1fr);
    gap: 0.8rem;
    padding: 0.6rem 0;
    border-top: 1px solid #e5e7e1;
  }
  dt { color: var(--muted); font-size: 0.66rem; font-weight: 750; }
  dd { min-width: 0; margin: 0; color: var(--ink); font-size: 0.7rem; overflow-wrap: anywhere; }
  dd.structured { white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.62rem; line-height: 1.55; }
  .empty { margin: 0; color: var(--muted); font-size: 0.7rem; }
  @media (max-width: 520px) {
    dl > div { grid-template-columns: 1fr; gap: 0.25rem; }
  }
</style>
