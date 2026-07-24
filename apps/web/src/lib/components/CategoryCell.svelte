<script lang="ts">
  import type { CategoryView, TransactionView } from './phase1-types.js';

  export let transaction: TransactionView;
  export let categories: CategoryView[] = [];
  export let onSave: (transactionId: string, categoryId: string, applyToMerchant: boolean) => Promise<void> = async () => undefined;

  let editing = false;
  let selected = '';
  let saving = false;
  let message = '';

  $: if (!editing) selected = transaction.categoryId ?? '';
  $: sourceLabel = transaction.categorySource
    ? transaction.categorySource.replace('user_', 'Your ').replace('_', ' ')
    : '';
  $: confidence = transaction.categoryConfidence == null ? null : Number(transaction.categoryConfidence);

  async function save(applyToMerchant: boolean) {
    if (!selected || saving) return;
    saving = true;
    message = '';
    try {
      await onSave(transaction.id, selected, applyToMerchant);
      editing = false;
    } catch (error) {
      message = error instanceof Error ? error.message : 'Could not save category.';
    } finally {
      saving = false;
    }
  }
</script>

<div class="category-cell">
  <button
    type="button"
    class="category-summary"
    aria-expanded={editing}
    aria-label={`Change category for ${transaction.merchantName ?? transaction.description}`}
    on:click={() => (editing = !editing)}
  >
    <span class="pill">{transaction.categoryName ?? 'Uncategorized'}</span>
    {#if sourceLabel}
      <small>{sourceLabel}{confidence != null && Number.isFinite(confidence) ? ` · ${Math.round(confidence * 100)}%` : ''}</small>
    {/if}
  </button>

  {#if editing}
    <div class="editor">
      <label>
        <span class="sr-only">New category</span>
        <select bind:value={selected} disabled={saving}>
          <option value="" disabled>Choose category</option>
          {#each categories.filter((category) => !category.archivedAt) as category}
            <option value={category.id}>{category.name}</option>
          {/each}
        </select>
      </label>
      <div class="actions">
        <button type="button" disabled={!selected || saving} on:click={() => save(false)}>This transaction</button>
        <button type="button" disabled={!selected || saving} on:click={() => save(true)}>Matching merchant</button>
        <button type="button" class="cancel" disabled={saving} on:click={() => (editing = false)}>Cancel</button>
      </div>
      <small class="hint">Matching merchant applies to current and future transactions with the same flow.</small>
      {#if message}<small class="error" role="alert">{message}</small>{/if}
    </div>
  {/if}
</div>

<style>
  .category-cell { position: relative; min-width: 138px; }
  .category-summary {
    display: grid;
    padding: 0;
    justify-items: start;
    gap: 0.25rem;
    color: inherit;
    border: 0;
    background: transparent;
    text-align: left;
  }
  .category-summary small { color: var(--muted); font-size: 0.58rem; text-transform: capitalize; }
  .editor {
    position: absolute;
    z-index: 12;
    top: calc(100% + 0.45rem);
    left: 0;
    display: grid;
    width: min(320px, calc(100vw - 3rem));
    gap: 0.55rem;
    padding: 0.75rem;
    border: 1px solid var(--line);
    border-radius: 11px;
    background: white;
    box-shadow: 0 14px 38px rgb(16 43 42 / 18%);
  }
  select { width: 100%; min-height: 38px; padding: 0 0.55rem; border: 1px solid var(--line); border-radius: 8px; background: #f8f7f2; font-size: 0.7rem; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .actions button { min-height: 33px; padding: 0.35rem 0.52rem; color: white; border: 1px solid var(--forest); border-radius: 7px; background: var(--forest); font-size: 0.62rem; font-weight: 750; }
  .actions button.cancel { color: var(--forest); border-color: var(--line); background: white; }
  .actions button:disabled { opacity: 0.45; }
  .hint { color: var(--muted); font-size: 0.57rem; line-height: 1.4; }
  .error { color: var(--danger); font-size: 0.6rem; }
</style>
