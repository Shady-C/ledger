<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { IngestAccepted, IngestResult, JobStatus } from '@ledger/shared-types';

  import { apiMessage } from '$lib/format.js';
  import type { AccountView } from './phase1-types.js';

  type IngestJobResponse = {
    id: string;
    kind?: 'ingest';
    status: JobStatus;
    result: IngestResult | null;
    error: string | null;
  };

  export let accounts: AccountView[] = [];
  export let onComplete: () => void = () => undefined;

  let accountId = '';
  let input: HTMLInputElement;
  let files: File[] = [];
  let dragging = false;
  let submitting = false;
  let message = '';
  let tone: 'neutral' | 'success' | 'error' = 'neutral';
  let pollTimer: ReturnType<typeof setTimeout> | undefined;

  $: if (accountId && !accounts.some((account) => account.id === accountId)) accountId = '';
  $: if (!accountId && accounts.length === 1) accountId = accounts[0]?.id ?? '';

  function choose(selected: FileList | File[]) {
    files = Array.from(selected).filter((file) => /\.(csv|xlsx|pdf|ofx|qfx)$/i.test(file.name));
    tone = 'neutral';
    message = files.length ? `${files.length} ${files.length === 1 ? 'statement' : 'statements'} ready` : '';
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    dragging = false;
    if (event.dataTransfer?.files) choose(event.dataTransfer.files);
  }

  async function poll(jobId: string, attempt = 0): Promise<void> {
    if (attempt > 600) {
      tone = 'error';
      message = 'The import is still running. Check back from this page in a few minutes.';
      submitting = false;
      return;
    }
    try {
      const response = await fetch(`/api/jobs/${jobId}`, { headers: { accept: 'application/json' } });
      if (!response.ok) throw new Error(await apiMessage(response, 'Could not check the import.'));
      const job = (await response.json()) as IngestJobResponse;
      if (job.status === 'done') {
        const added = job.result?.added ?? 0;
        const skipped = job.result?.skipped ?? 0;
        const issues = job.result?.files.filter((file) =>
          file.reconciliation && (
            !['ok', 'pending'].includes(file.reconciliation.status)
            || file.reconciliation.coverageGaps.length > 0
          )
        ).length ?? 0;
        tone = issues ? 'error' : 'success';
        message = issues
          ? `Import complete with ${issues} reconciliation ${issues === 1 ? 'issue' : 'issues'}; ${added} added.`
          : `Import complete: ${added} added${skipped ? `, ${skipped} already recorded` : ''}.`;
        submitting = false;
        files = [];
        if (input) input.value = '';
        onComplete();
        return;
      }
      if (job.status === 'failed' || job.status === 'needs_ai') {
        tone = 'error';
        const addedBeforeStop = job.result?.added ?? 0;
        message = job.status === 'needs_ai'
          ? `${addedBeforeStop ? `${addedBeforeStop} added. ` : ''}At least one statement needs format support before Ledger can safely import it.`
          : `${addedBeforeStop ? `${addedBeforeStop} added before the import stopped. ` : ''}${job.error || 'The import failed. Check the worker logs for details.'}`;
        submitting = false;
        onComplete();
        return;
      }
      message = job.status === 'claimed' ? 'Reading and reconciling your statements…' : 'Import queued…';
      pollTimer = setTimeout(() => void poll(jobId, attempt + 1), 1500);
    } catch (error) {
      tone = 'error';
      message = error instanceof Error ? error.message : 'Could not check the import.';
      submitting = false;
    }
  }

  async function upload() {
    if (!accountId || files.length === 0 || submitting) return;
    submitting = true;
    tone = 'neutral';
    message = 'Securing your upload…';
    const form = new FormData();
    form.set('accountId', accountId);
    files.forEach((file) => form.append('files', file));

    try {
      const response = await fetch('/api/ingest', { method: 'POST', body: form });
      if (!response.ok) throw new Error(await apiMessage(response, 'The upload could not be started.'));
      const accepted = (await response.json()) as IngestAccepted;
      message = 'Import queued…';
      await poll(accepted.jobId);
    } catch (error) {
      tone = 'error';
      message = error instanceof Error ? error.message : 'The upload could not be started.';
      submitting = false;
    }
  }

  onDestroy(() => {
    if (pollTimer) clearTimeout(pollTimer);
  });
</script>

<section class="upload-card" aria-labelledby="upload-title">
  <div class="copy">
    <p class="eyebrow">Statement inbox</p>
    <h2 id="upload-title">Turn statements into an auditable ledger.</h2>
    <p class="support">CSV, XLSX, OFX/QFX, or a supported deterministic PDF such as I&amp;M Tanzania TZS or Wealthsimple Chequing. Repeat uploads are safely skipped.</p>
  </div>

  <form on:submit|preventDefault={upload}>
    <label class="account-label" for="upload-account">Import into</label>
    <select id="upload-account" bind:value={accountId} disabled={submitting || accounts.length === 0}>
      <option value="" disabled>Select an account</option>
      {#each accounts as account}
        <option value={account.id}>{account.displayName} · {account.nativeCurrency}</option>
      {/each}
    </select>

    <div
      class:dragging
      class="dropzone"
      role="button"
      tabindex={accounts.length ? 0 : -1}
      aria-disabled={accounts.length === 0 || submitting}
      on:click={() => !submitting && accounts.length && input?.click()}
      on:keydown={(event) => {
        if ((event.key === 'Enter' || event.key === ' ') && !submitting && accounts.length) {
          event.preventDefault();
          input?.click();
        }
      }}
      on:dragenter|preventDefault={() => (dragging = true)}
      on:dragover|preventDefault={() => (dragging = true)}
      on:dragleave={() => (dragging = false)}
      on:drop={drop}
    >
      <input
        class="sr-only"
        bind:this={input}
        type="file"
        accept=".csv,.xlsx,.pdf,.ofx,.qfx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pdf,application/x-ofx"
        multiple
        disabled={accounts.length === 0 || submitting}
        on:change={(event) => choose(event.currentTarget.files ?? [])}
      />
      <span class="upload-icon" aria-hidden="true">↑</span>
      <span>
        <strong>{files.length ? 'Change selection' : 'Drop statements here'}</strong>
        <small>{accounts.length ? 'or choose files from your device' : 'Add an account before importing'}</small>
      </span>
    </div>

    <button class="submit" type="submit" disabled={!accountId || files.length === 0 || submitting}>
      {submitting ? 'Importing…' : files.length ? `Import ${files.length}` : 'Choose statements'}
    </button>
    <p class:error={tone === 'error'} class:success={tone === 'success'} class="status" aria-live="polite">
      {message || 'Raw files stay in your self-hosted object store.'}
    </p>
  </form>
</section>

<style>
  .upload-card {
    position: relative;
    display: grid;
    grid-template-columns: minmax(0, 0.9fr) minmax(280px, 1.1fr);
    gap: clamp(1.5rem, 4vw, 3.5rem);
    overflow: hidden;
    padding: clamp(1.25rem, 3vw, 2.25rem);
    color: white;
    border-radius: 24px;
    background: var(--forest);
    box-shadow: 0 24px 70px rgb(13 39 37 / 18%);
  }

  .upload-card::after {
    position: absolute;
    right: -90px;
    bottom: -120px;
    width: 290px;
    height: 290px;
    border: 1px solid rgb(167 215 200 / 26%);
    border-radius: 50%;
    box-shadow: 0 0 0 42px rgb(167 215 200 / 5%), 0 0 0 84px rgb(167 215 200 / 4%);
    content: '';
    pointer-events: none;
  }

  .copy,
  form {
    position: relative;
    z-index: 1;
  }

  .eyebrow {
    margin: 0 0 0.65rem;
    color: var(--mint);
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  h2 {
    max-width: 15ch;
    margin: 0;
    font-size: clamp(1.7rem, 4vw, 2.8rem);
    line-height: 1.04;
    letter-spacing: -0.055em;
  }

  .support {
    max-width: 38ch;
    margin: 1rem 0 0;
    color: #bcd0ca;
    font-size: 0.88rem;
    line-height: 1.55;
  }

  form {
    display: grid;
    grid-template-columns: 1fr auto;
    align-content: start;
    gap: 0.7rem;
  }

  .account-label {
    grid-column: 1 / -1;
    color: #bcd0ca;
    font-size: 0.7rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  select {
    grid-column: 1 / -1;
    width: 100%;
    padding: 0.75rem 0.8rem;
    color: white;
    border: 1px solid rgb(255 255 255 / 20%);
    border-radius: 10px;
    background: #183b39;
  }

  select:disabled {
    opacity: 0.55;
  }

  .dropzone {
    display: flex;
    grid-column: 1 / -1;
    align-items: center;
    gap: 0.8rem;
    min-height: 98px;
    padding: 0.95rem;
    border: 1px dashed rgb(167 215 200 / 52%);
    border-radius: 13px;
    background: rgb(255 255 255 / 4%);
    transition: background 150ms ease, border-color 150ms ease;
  }

  .dropzone:not([aria-disabled='true']):hover,
  .dropzone.dragging {
    border-color: var(--mint);
    background: rgb(167 215 200 / 9%);
  }

  .dropzone[aria-disabled='true'] {
    cursor: not-allowed;
    opacity: 0.6;
  }

  .upload-icon {
    display: grid;
    flex: 0 0 auto;
    width: 43px;
    height: 43px;
    place-items: center;
    color: var(--forest);
    border-radius: 50%;
    background: var(--mint);
    font-size: 1.3rem;
    font-weight: 800;
  }

  .dropzone span:last-child {
    display: grid;
    gap: 0.2rem;
  }

  .dropzone strong {
    font-size: 0.88rem;
  }

  .dropzone small {
    color: #a9beb8;
    font-size: 0.72rem;
  }

  .submit {
    min-height: 42px;
    padding: 0.65rem 1rem;
    color: var(--forest);
    border: 0;
    border-radius: 10px;
    background: var(--mint);
    font-size: 0.8rem;
    font-weight: 800;
  }

  .submit:disabled {
    opacity: 0.45;
  }

  .status {
    align-self: center;
    margin: 0;
    color: #a9beb8;
    font-size: 0.7rem;
    line-height: 1.4;
  }

  .status.error { color: #ffc4b5; }
  .status.success { color: #b8e7d7; }

  @media (max-width: 740px) {
    .upload-card {
      grid-template-columns: 1fr;
    }

    h2 { max-width: 20ch; }
  }

  @media (max-width: 440px) {
    form { grid-template-columns: 1fr; }
    .submit, .status { grid-column: 1; }
  }
</style>
