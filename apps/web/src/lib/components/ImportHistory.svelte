<script lang="ts">
  import type { IngestFileResult, JobResponse } from '@ledger/shared-types';
  import { dateTime, readJson } from './api-client.js';

  type JobListItem = {
    id: string;
    kind: 'ingest' | 'categorize' | 'fx_refresh' | 'base_currency_rebuild' | 'analytics_refresh';
    status: 'queued' | 'claimed' | 'done' | 'failed' | 'needs_ai';
    createdAt: string;
    finishedAt: string | null;
    retryCount: number;
    maxRetries: number;
  };

  export let jobs: JobListItem[] = [];
  export let loading = false;
  export let onRefresh: () => void = () => undefined;

  let expandedId = '';
  let detail: JobResponse | null = null;
  let detailError = '';
  let loadingDetail = false;

  function statusLabel(status: JobListItem['status']) {
    return status === 'needs_ai' ? 'Needs format support' : status.replace('_', ' ');
  }

  function fileStatusLabel(status: string) {
    return status === 'needs_ai' ? 'needs format support' : status.replaceAll('_', ' ');
  }

  function statementLabel(fileKey: string) {
    const storedName = fileKey.split('/').at(-1) ?? '';
    const digestName = /^([a-f\d]{64})\.(csv|xlsx|pdf|ofx|qfx)$/i.exec(storedName);
    if (!digestName) return 'Statement file';
    const digest = digestName[1] ?? '';
    const format = digestName[2] ?? '';
    return `${format.toUpperCase()} statement · …${digest.slice(-3)}`;
  }

  function displayReason(file: Pick<IngestFileResult, 'fileKey' | 'status' | 'reason'>) {
    if (file.status !== 'needs_ai') return file.reason ?? '';
    return /\.pdf$/i.test(file.fileKey)
      ? 'This PDF layout could not be parsed safely.'
      : 'This statement layout could not be parsed safely.';
  }

  async function toggle(job: JobListItem) {
    if (expandedId === job.id) {
      expandedId = '';
      detail = null;
      return;
    }
    expandedId = job.id;
    detail = null;
    detailError = '';
    loadingDetail = true;
    try {
      detail = await readJson<JobResponse>(`/api/jobs/${job.id}`, 'The import details could not be loaded.');
    } catch (error) {
      detailError = error instanceof Error ? error.message : 'The import details could not be loaded.';
    } finally {
      loadingDetail = false;
    }
  }
</script>

<section class="panel history" aria-labelledby="import-history-title">
  <div class="panel-heading">
    <div><h2 id="import-history-title">Import history</h2><p>Reconciliation, idempotency, and parser outcomes for each queued import.</p></div>
    <button class="text-button" type="button" on:click={onRefresh}>Refresh</button>
  </div>

  {#if loading}
    <div class="loading" aria-label="Loading import history" aria-busy="true">{#each Array(4) as _}<span></span>{/each}</div>
  {:else if jobs.length === 0}
    <div class="empty-state"><strong>No imports yet</strong><p>Your first import job will appear here.</p></div>
  {:else}
    <ol>
      {#each jobs as job}
        <li>
          <button class="job-row" type="button" aria-expanded={expandedId === job.id} on:click={() => toggle(job)}>
            <span class:failed={job.status === 'failed'} class:needs-ai={job.status === 'needs_ai'} class:done={job.status === 'done'} class="status-dot" aria-hidden="true"></span>
            <span class="job-copy"><strong>{statusLabel(job.status)}</strong><small>{dateTime(job.createdAt)} · {job.id.slice(0, 8)}</small></span>
            {#if job.status !== 'done' && job.status !== 'needs_ai'}
              <span class="retry">{job.retryCount}/{job.maxRetries} retries</span>
            {/if}
            <span class="expand-glyph" aria-hidden="true">{expandedId === job.id ? '−' : '+'}</span>
          </button>

          {#if expandedId === job.id}
            <div class="job-detail">
              {#if loadingDetail}
                <p aria-busy="true">Loading job details…</p>
              {:else if detailError}
                <p class="error" role="alert">{detailError}</p>
              {:else if detail?.kind === 'ingest'}
                {#if detail.error}<p class="error">{detail.error}</p>{/if}
                {#if detail.result}
                  <div class="totals"><span><strong>{detail.result.added}</strong> added</span><span><strong>{detail.result.skipped}</strong> skipped</span><span><strong>{detail.result.files.length}</strong> files</span></div>
                  <ul class="files">
                    {#each detail.result.files as file}
                      <li>
                        <div><strong>{statementLabel(file.fileKey)}</strong><small>{file.adapter} · {fileStatusLabel(file.status)}</small></div>
                        {#if file.reconciliation}
                          <span class:issue={file.reconciliation.status !== 'ok'} class="pill">{file.reconciliation.status}</span>
                        {:else if file.reason || file.status === 'needs_ai'}
                          <span class="reason">{displayReason(file)}</span>
                        {/if}
                      </li>
                    {/each}
                  </ul>
                {:else}
                  <p>{job.status === 'needs_ai' ? 'This statement format is not supported yet. No further retries are scheduled.' : 'The worker has not produced a result yet.'}</p>
                {/if}
              {:else if detail}
                <p>This {detail.kind.replaceAll('_', ' ')} job is shown in the global job queue.</p>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</section>

<style>
  .history { min-width: 0; }
  ol,
  .files { padding: 0; margin: 0; list-style: none; }
  ol > li { border-top: 1px solid #e8e9e3; }
  .job-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; width: 100%; min-height: 62px; padding: 0.6rem 0.2rem; align-items: center; gap: 0.7rem; color: var(--ink); border: 0; background: transparent; text-align: left; }
  .status-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--gold); box-shadow: 0 0 0 4px rgb(218 183 91 / 14%); }
  .status-dot.done { background: var(--success); box-shadow: 0 0 0 4px rgb(35 122 100 / 12%); }
  .status-dot.failed { background: var(--danger); }
  .status-dot.needs-ai { background: var(--coral); }
  .job-copy { display: grid; gap: 0.2rem; }
  .job-copy strong { font-size: 0.74rem; text-transform: capitalize; }
  .expand-glyph { grid-column: 4; }
  .job-copy small,
  .retry { color: var(--muted); font-size: 0.61rem; }
  .job-detail { padding: 0.2rem 0.2rem 0.9rem 1.85rem; color: var(--muted); font-size: 0.68rem; line-height: 1.5; }
  .job-detail p { margin: 0.25rem 0; }
  .job-detail .error { color: var(--danger); }
  .totals { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 0.65rem; }
  .totals strong { color: var(--ink); }
  .files { border: 1px solid #e5e6df; border-radius: 9px; background: #f8f7f2; }
  .files li { display: flex; min-height: 48px; padding: 0.5rem 0.65rem; align-items: center; justify-content: space-between; gap: 0.8rem; border-top: 1px solid #e5e6df; }
  .files li:first-child { border-top: 0; }
  .files li > div { display: grid; min-width: 0; gap: 0.12rem; }
  .files li strong { overflow: hidden; color: var(--ink); font-size: 0.66rem; text-overflow: ellipsis; white-space: nowrap; }
  .files li small { font-size: 0.58rem; }
  .pill.issue { color: var(--danger); background: var(--coral-soft); }
  .reason { max-width: 45%; color: var(--danger); font-size: 0.58rem; text-align: right; }
  .loading { display: grid; gap: 0.5rem; }
  .loading span { height: 54px; border-radius: 9px; background: #efefe9; animation: pulse 1s ease-in-out infinite alternate; }
  @keyframes pulse { to { opacity: 0.5; } }
  @media (max-width: 520px) {
    .retry { display: none; }
    .job-row { grid-template-columns: auto minmax(0, 1fr) auto; }
    .expand-glyph { grid-column: 3; }
    .job-detail { padding-left: 0; }
    .files li { align-items: flex-start; }
  }
</style>
