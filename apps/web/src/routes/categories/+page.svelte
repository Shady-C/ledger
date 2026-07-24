<script lang="ts">
  import { onMount } from 'svelte';
  import type {
    CategorizationProposal,
    CategoriesResponse,
    UnresolvedMerchantFlow
  } from '@ledger/shared-types';

  import CategoryForm from '$lib/components/CategoryForm.svelte';
  import { dateTime, readJson, readOptionalJson, sendJson } from '$lib/components/api-client.js';
  import type { CategoryView } from '$lib/components/phase1-types.js';

  type Proposal = CategorizationProposal;

  type CategoryDraft = { name: string; kind: CategoryView['kind']; parentId: string | null };

  let categories: CategoryView[] = [];
  let proposals: Proposal[] = [];
  let unresolved: UnresolvedMerchantFlow[] = [];
  let editingCategory: CategoryView | null = null;
  let loading = true;
  let pageError = '';
  let message = '';
  let categorizing = false;
  let reviewingId = '';

  $: activeCategories = categories.filter((category) => !category.archivedAt);
  $: archivedCategories = categories.filter((category) => category.archivedAt);
  $: pendingProposals = proposals.filter((proposal) => proposal.status === 'pending');

  async function load() {
    loading = true;
    pageError = '';
    try {
      const [categoryResult, proposalResult, unresolvedResult] = await Promise.all([
        readJson<CategoriesResponse>('/api/categories'),
        readOptionalJson<{ proposals: CategorizationProposal[] }>('/api/categories/proposals').catch(() => null),
        readOptionalJson<{ unresolved: UnresolvedMerchantFlow[] }>('/api/categories/unresolved').catch(() => null)
      ]);
      categories = categoryResult.categories;
      proposals = proposalResult?.proposals ?? [];
      unresolved = unresolvedResult?.unresolved ?? [];
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Categories are temporarily unavailable.';
    } finally {
      loading = false;
    }
  }

  async function saveCategory(draft: CategoryDraft) {
    const url = editingCategory ? `/api/categories/${editingCategory.id}` : '/api/categories';
    await sendJson(url, editingCategory ? 'PATCH' : 'POST', draft);
    message = editingCategory ? `${draft.name} was updated.` : `${draft.name} was added.`;
    editingCategory = null;
    await load();
  }

  async function setArchived(category: CategoryView, archived: boolean) {
    pageError = '';
    try {
      await sendJson(`/api/categories/${category.id}`, 'PATCH', { archived });
      message = `${category.name} was ${archived ? 'archived' : 'restored'}.`;
      await load();
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The category could not be changed.';
    }
  }

  async function decide(proposal: Proposal, decision: 'accept' | 'reject') {
    reviewingId = proposal.id;
    pageError = '';
    try {
      await sendJson(`/api/categories/proposals/${proposal.id}`, 'PATCH', { decision });
      message = `${proposal.merchantName} proposal ${decision === 'accept' ? 'accepted' : 'rejected'}.`;
      await load();
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The proposal could not be reviewed.';
    } finally {
      reviewingId = '';
    }
  }

  async function categorize(mode: 'incremental' | 'backfill') {
    if (categorizing) return;
    categorizing = true;
    pageError = '';
    try {
      const accepted = await sendJson<{ jobId: string; kind: 'categorize'; status: 'queued' | 'claimed' }>(
        '/api/categories/categorize',
        'POST',
        { mode }
      );
      message = `${mode === 'backfill' ? 'Unresolved-merchant scan' : 'Categorization'} queued (${accepted.jobId.slice(0, 8)}…).`;
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Categorization could not be queued.';
    } finally {
      categorizing = false;
    }
  }

  function categoryName(proposal: Proposal) {
    return proposal.proposedCategoryName
      ?? categories.find((category) => category.id === proposal.proposedCategoryId)?.name
      ?? 'New category proposal';
  }

  onMount(load);
</script>

<svelte:head>
  <title>Categories · Ledger</title>
  <meta name="description" content="Manage your category taxonomy and review AI categorization proposals." />
</svelte:head>

<div class="page">
  <header class="page-header">
    <div class="page-header-copy">
      <p class="eyebrow">Taxonomy &amp; review</p>
      <h1>Automation, with the final say yours.</h1>
      <p class="lede">Rules handle known patterns. AI only proposes allowed categories or asks you to approve a new one; low-confidence choices wait here.</p>
    </div>
    <div class="header-actions">
      <button class="button-secondary" type="button" disabled={categorizing} on:click={() => categorize('backfill')}>Scan unresolved</button>
      <button class="button" type="button" disabled={categorizing} on:click={() => categorize('incremental')}>{categorizing ? 'Queuing…' : 'Categorize new merchants'}</button>
    </div>
  </header>

  {#if pageError}
    <div class="status-banner" role="alert"><strong>Categories need attention.</strong><span>{pageError}</span><button class="button-secondary" type="button" on:click={load}>Try again</button></div>
  {:else if message}
    <div class="status-banner success" role="status"><strong>Updated.</strong><span>{message}</span><button class="text-button" type="button" on:click={() => (message = '')}>Dismiss</button></div>
  {/if}

  <section class="panel unresolved-panel" aria-labelledby="unresolved-title">
    <div class="panel-heading">
      <div><h2 id="unresolved-title">Unresolved merchants</h2><p>Distinct merchant-and-flow pairs still using the protected fallback category.</p></div>
      <span class="count">{unresolved.length}</span>
    </div>
    {#if loading}
      <div class="skeleton-block"></div>
    {:else if unresolved.length === 0}
      <div class="empty-state"><strong>Nothing unresolved</strong><p>New merchant-and-flow pairs will appear here before or after a categorization retry.</p></div>
    {:else}
      <ul class="unresolved-list">
        {#each unresolved as item}
          <li>
            <span><strong>{item.merchantName}</strong><small>{item.firstSeen}–{item.lastSeen}</small></span>
            <span><span class="pill">{item.flowType}</span><strong>{item.transactionCount} {item.transactionCount === 1 ? 'transaction' : 'transactions'}</strong></span>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="panel review-panel" aria-labelledby="review-title">
    <div class="panel-heading">
      <div><h2 id="review-title">Needs your review</h2><p>Low-confidence assignments and every suggested new category stay pending until reviewed.</p></div>
      <span class="count">{pendingProposals.length}</span>
    </div>

    {#if loading}
      <div class="proposal-grid"><div class="skeleton-block"></div><div class="skeleton-block"></div></div>
    {:else if pendingProposals.length === 0}
      <div class="empty-state"><strong>No pending proposals</strong><p>New unresolved merchant-and-flow pairs will appear after categorization runs.</p></div>
    {:else}
      <div class="proposal-grid">
        {#each pendingProposals as proposal}
          <article class="proposal-card">
            <div class="proposal-top"><span class="pill">{proposal.flowType}</span><strong>{Math.round(Number(proposal.confidence) * 100)}% confidence</strong></div>
            <div><h3>{proposal.merchantName}</h3><p>Suggested: <strong>{categoryName(proposal)}</strong>{proposal.proposedCategoryKind ? ` · ${proposal.proposedCategoryKind}` : ''}</p></div>
            <small>Proposed {dateTime(proposal.createdAt)} · {proposal.model}</small>
            <div class="proposal-actions">
              <button class="button-secondary" type="button" disabled={reviewingId === proposal.id} on:click={() => decide(proposal, 'reject')}>Reject</button>
              <button class="button" type="button" disabled={reviewingId === proposal.id} on:click={() => decide(proposal, 'accept')}>{reviewingId === proposal.id ? 'Saving…' : 'Accept'}</button>
            </div>
          </article>
        {/each}
      </div>
    {/if}
  </section>

  <section class="taxonomy-grid">
    <article class="panel" aria-labelledby="taxonomy-title">
      <div class="panel-heading"><div><h2 id="taxonomy-title">Category taxonomy</h2><p>{activeCategories.length} active · {archivedCategories.length} archived</p></div></div>
      {#if loading}
        <div class="skeleton-block"></div>
      {:else}
        <div class="category-groups">
          {#each ['spend', 'income', 'transfer', 'fee'] as kind}
            <section aria-labelledby={`${kind}-title`}>
              <h3 id={`${kind}-title`}>{kind}</h3>
              <ul>
                {#each activeCategories.filter((category) => category.kind === kind) as category}
                  <li class:child={Boolean(category.parentId)}>
                    <span>{category.name}{category.isProtected ? ' · protected' : ''}</span>
                    <span class="row-actions">
                      <button class="text-button" type="button" on:click={() => (editingCategory = category)}>Edit</button>
                      {#if !category.isProtected}<button class="text-button archive" type="button" on:click={() => setArchived(category, true)}>Archive</button>{/if}
                    </span>
                  </li>
                {/each}
              </ul>
            </section>
          {/each}
        </div>
        {#if archivedCategories.length}
          <details class="archived">
            <summary>Archived categories ({archivedCategories.length})</summary>
            <ul>{#each archivedCategories as category}<li><span>{category.name}</span><button class="text-button" type="button" on:click={() => setArchived(category, false)}>Restore</button></li>{/each}</ul>
          </details>
        {/if}
      {/if}
    </article>

    <article class="panel form-panel" aria-labelledby="category-form-title">
      <div class="panel-heading"><div><h2 id="category-form-title">{editingCategory ? `Edit ${editingCategory.name}` : 'Add a category'}</h2><p>Categories are labels only; arithmetic remains deterministic.</p></div></div>
      <CategoryForm category={editingCategory} {categories} onSubmit={saveCategory} onCancel={() => (editingCategory = null)} />
    </article>
  </section>
</div>

<style>
  .header-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 0.55rem; }
  .count { display: grid; width: 34px; height: 34px; place-items: center; color: var(--forest); border-radius: 50%; background: var(--mint); font-size: 0.72rem; font-weight: 850; }
  .proposal-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.7rem; }
  .proposal-card { display: grid; min-height: 200px; padding: 1rem; align-content: space-between; gap: 0.8rem; border: 1px solid #e2e4dd; border-radius: 14px; background: #f8f7f2; }
  .proposal-top { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
  .proposal-top > strong { color: var(--coral); font-size: 0.64rem; }
  .proposal-card h3,
  .proposal-card p { margin: 0; }
  .proposal-card h3 { font-size: 0.92rem; letter-spacing: -0.02em; }
  .proposal-card p { margin-top: 0.3rem; color: var(--muted); font-size: 0.68rem; }
  .proposal-card small { color: var(--muted); font-size: 0.58rem; }
  .proposal-actions { display: flex; justify-content: flex-end; gap: 0.4rem; }
  .unresolved-list { display: grid; padding: 0; margin: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.5rem; list-style: none; }
  .unresolved-list li { display: flex; min-width: 0; padding: 0.75rem; align-items: center; justify-content: space-between; gap: 0.8rem; border: 1px solid #e2e4dd; border-radius: 12px; background: #f8f7f2; }
  .unresolved-list li > span { display: grid; min-width: 0; gap: 0.25rem; }
  .unresolved-list li > span:last-child { justify-items: end; }
  .unresolved-list strong { overflow: hidden; font-size: 0.7rem; text-overflow: ellipsis; white-space: nowrap; }
  .unresolved-list small { color: var(--muted); font-size: 0.56rem; }
  .taxonomy-grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(330px, 0.9fr); gap: 1rem; align-items: start; }
  .form-panel { position: sticky; top: 86px; }
  .category-groups { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; }
  .category-groups h3 { margin: 0 0 0.35rem; color: var(--coral); font-size: 0.66rem; letter-spacing: 0.09em; text-transform: uppercase; }
  .category-groups ul,
  .archived ul { padding: 0; margin: 0; list-style: none; }
  .category-groups li,
  .archived li { display: flex; min-height: 38px; padding: 0.2rem 0; align-items: center; justify-content: space-between; gap: 0.5rem; border-top: 1px solid #e9e9e3; font-size: 0.7rem; }
  .category-groups li.child { padding-left: 0.8rem; }
  .category-groups li.child > span:first-child::before { color: #a5aca8; content: '↳ '; }
  .row-actions { display: flex; }
  .row-actions .archive { color: var(--danger); }
  .archived { margin-top: 1rem; padding-top: 0.7rem; border-top: 1px solid var(--line); }
  .archived summary { color: var(--muted); cursor: pointer; font-size: 0.68rem; font-weight: 750; }
  @media (max-width: 940px) {
    .proposal-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .taxonomy-grid { grid-template-columns: 1fr; }
    .form-panel { position: static; }
  }
  @media (max-width: 620px) {
    .header-actions,
    .header-actions > * { width: 100%; }
    .proposal-grid,
    .unresolved-list,
    .category-groups { grid-template-columns: 1fr; }
  }
</style>
