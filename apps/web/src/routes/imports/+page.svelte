<script lang="ts">
  import { onMount } from 'svelte';
  import type { AccountsResponse } from '@ledger/shared-types';

  import ImportHistory from '$lib/components/ImportHistory.svelte';
  import UploadPanel from '$lib/components/UploadPanel.svelte';
  import { readJson, readOptionalJson } from '$lib/components/api-client.js';
  import type { AccountView } from '$lib/components/phase1-types.js';

  type JobListItem = {
    id: string;
    kind: 'ingest' | 'categorize' | 'fx_refresh' | 'base_currency_rebuild';
    status: 'queued' | 'claimed' | 'done' | 'failed' | 'needs_ai';
    createdAt: string;
    finishedAt: string | null;
    retryCount: number;
    maxRetries: number;
  };
  type JobsResponse = {
    jobs: JobListItem[];
    page: number;
    pageSize: number;
    total: number;
    totalPages: number;
  };

  let accounts: AccountView[] = [];
  let jobs: JobListItem[] = [];
  let loading = true;
  let historyLoading = true;
  let pageError = '';

  async function loadHistory() {
    historyLoading = true;
    try {
      const result = await readOptionalJson<JobsResponse>('/api/jobs?kind=ingest&pageSize=25');
      jobs = result?.jobs ?? [];
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Import history is temporarily unavailable.';
    } finally {
      historyLoading = false;
    }
  }

  async function load() {
    loading = true;
    pageError = '';
    try {
      const accountResult = await readJson<AccountsResponse>('/api/accounts');
      accounts = accountResult.accounts;
      await loadHistory();
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Imports are temporarily unavailable.';
    } finally {
      loading = false;
    }
  }

  async function importComplete() {
    await loadHistory();
  }

  onMount(load);
</script>

<svelte:head>
  <title>Imports · Ledger</title>
  <meta name="description" content="Import and reconcile CSV, XLSX, OFX/QFX, and deterministic PDF statements." />
</svelte:head>

<div class="page">
  <header class="page-header">
    <div class="page-header-copy">
      <p class="eyebrow">Statement inbox</p>
      <h1>From statement to reconciled record.</h1>
      <p class="lede">Import known formats directly. Unknown CSV and spreadsheet layouts can receive a redacted AI column map before any financial row is persisted.</p>
    </div>
  </header>

  {#if pageError}
    <div class="status-banner" role="alert"><strong>Imports need attention.</strong><span>{pageError}</span><button class="button-secondary" type="button" on:click={load}>Try again</button></div>
  {/if}

  {#if !loading && accounts.length === 0}
    <div class="status-banner info"><strong>Add an account first.</strong><span>Each statement must be tied to an asset account or credit card before import.</span><a class="text-button" href="/accounts">Go to accounts</a></div>
  {/if}

  <UploadPanel {accounts} onComplete={importComplete} />

  <section class="format-notes" aria-label="Supported import formats">
    <article><span>CSV / XLSX</span><strong>Known or safely mapped</strong><p>Unknown columns use headers and up to five redacted rows; reconciliation still decides whether persistence is allowed.</p></article>
    <article><span>OFX / QFX</span><strong>Bank and card statements</strong><p>FITID preserves transaction identity. Investment statements remain unsupported.</p></article>
    <article><span>PDF</span><strong>Deterministic tables only</strong><p>Irregular PDF AI extraction remains outside Phase 1.</p></article>
  </section>

  <ImportHistory {jobs} loading={historyLoading} onRefresh={loadHistory} />
</div>

<style>
  .format-notes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.7rem; }
  .format-notes article { display: grid; min-height: 140px; padding: 0.9rem; align-content: start; gap: 0.4rem; border: 1px solid var(--line); border-radius: 14px; background: rgb(252 251 247 / 65%); }
  .format-notes span { color: var(--coral); font-size: 0.61rem; font-weight: 850; letter-spacing: 0.09em; text-transform: uppercase; }
  .format-notes strong { font-size: 0.8rem; }
  .format-notes p { margin: 0; color: var(--muted); font-size: 0.65rem; line-height: 1.5; }
  @media (max-width: 760px) { .format-notes { grid-template-columns: 1fr; } .format-notes article { min-height: 0; } }
</style>
