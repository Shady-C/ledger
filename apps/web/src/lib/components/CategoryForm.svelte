<script lang="ts">
  import type { CategoryView } from './phase1-types.js';

  type CategoryDraft = {
    name: string;
    kind: CategoryView['kind'];
    parentId: string | null;
  };

  export let category: CategoryView | null = null;
  export let categories: CategoryView[] = [];
  export let onSubmit: (draft: CategoryDraft) => Promise<void> = async () => undefined;
  export let onCancel: () => void = () => undefined;

  let name = '';
  let kind: CategoryView['kind'] = 'spend';
  let parentId = '';
  let saving = false;
  let message = '';
  let initializedFor: string | null | undefined = undefined;

  $: if (initializedFor !== (category?.id ?? null)) {
    initializedFor = category?.id ?? null;
    name = category?.name ?? '';
    kind = category?.kind ?? 'spend';
    parentId = category?.parentId ?? '';
    message = '';
  }
  $: parentOptions = categories.filter((candidate) =>
    candidate.id !== category?.id && !candidate.parentId && !candidate.archivedAt && candidate.kind === kind
  );
  $: if (parentId && !parentOptions.some((candidate) => candidate.id === parentId)) parentId = '';

  async function submit() {
    if (!name.trim()) return;
    saving = true;
    message = '';
    try {
      await onSubmit({ name: name.trim(), kind, parentId: parentId || null });
      if (!category) name = '';
    } catch (error) {
      message = error instanceof Error ? error.message : 'The category could not be saved.';
    } finally {
      saving = false;
    }
  }
</script>

<form class="form-grid" on:submit|preventDefault={submit}>
  <label class="field">
    <span>Category name</span>
    <input bind:value={name} required maxlength="120" placeholder="Groceries" />
  </label>
  <label class="field">
    <span>Flow kind</span>
    <select bind:value={kind}>
      <option value="spend">Spend</option>
      <option value="income">Income</option>
      <option value="transfer">Transfer</option>
      <option value="fee">Fee</option>
    </select>
  </label>
  <label class="field parent-field">
    <span>Parent category</span>
    <select bind:value={parentId}>
      <option value="">Top level</option>
      {#each parentOptions as parent}<option value={parent.id}>{parent.name}</option>{/each}
    </select>
  </label>
  <div class="form-actions">
    {#if message}<span class="form-message" role="alert">{message}</span>{/if}
    {#if category}<button class="button-secondary" type="button" on:click={onCancel}>Cancel</button>{/if}
    <button class="button" type="submit" disabled={!name.trim() || saving}>{saving ? 'Saving…' : category ? 'Save category' : 'Add category'}</button>
  </div>
</form>

<style>
  .parent-field { grid-column: 1 / -1; }
  .form-message { margin-right: auto; color: var(--danger); font-size: 0.68rem; }
</style>
