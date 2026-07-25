<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import type {
    InsightSensitivity,
    InsightSettingsResponse,
    InsightSummaryResponse,
    MarketCode,
    SettingsResponse
  } from '@ledger/shared-types';
  import { dateTime, readJson, readOptionalJson, sendJson } from '$lib/components/api-client.js';
  import { updateSettings } from '$lib/market-scope.js';

  type HealthResponse = { status: 'ready' | 'unavailable' };
  type JobResponse = { id: string; status: 'queued' | 'claimed' | 'done' | 'failed'; error?: string | null };
  type MaintenanceJob = JobResponse & { kind: string; createdAt: string; finishedAt: string | null };
  type JobsResponse = { jobs: MaintenanceJob[] };

  let settings: SettingsResponse | null = null;
  let profile: MarketCode | '' = '';
  let savedProfile: MarketCode | '' = '';
  let sensitivity: InsightSensitivity = 'balanced';
  let savedSensitivity: InsightSensitivity = 'balanced';
  let summary: InsightSummaryResponse | null = null;
  let health: HealthResponse | null = null;
  let maintenanceJobs: MaintenanceJob[] = [];
  let loading = true;
  let savingProfile = false;
  let savingSensitivity = false;
  let rebuilding = false;
  let switchingCurrency = false;
  let targetCurrency: 'CAD' | 'TZS' = 'CAD';
  let currencyConfirmed = false;
  let pageError = '';
  let message = '';
  let pollTimer: ReturnType<typeof setTimeout> | undefined;

  async function load() {
    loading = true;
    pageError = '';
    try {
      const [settingsResult, insightSettings, insightSummary, healthResult, jobsResult] = await Promise.all([
        readJson<SettingsResponse>('/api/settings'),
        readOptionalJson<InsightSettingsResponse>('/api/insights/settings').catch(() => null),
        readOptionalJson<InsightSummaryResponse>('/api/insights/summary?range=12m').catch(() => null),
        fetch('/api/health', { cache: 'no-store', headers: { accept: 'application/json' } })
          .then(async (response) => (await response.json()) as HealthResponse)
          .catch(() => ({ status: 'unavailable' as const })),
        readOptionalJson<JobsResponse>('/api/jobs?pageSize=10').catch(() => null)
      ]);
      settings = settingsResult;
      savedProfile = settingsResult.marketProfile ?? '';
      profile = settingsResult.marketProfile ?? '';
      targetCurrency = settingsResult.baseCurrency === 'TZS' ? 'TZS' : 'CAD';
      if (insightSettings) {
        sensitivity = insightSettings.settings.sensitivity;
        savedSensitivity = insightSettings.settings.sensitivity;
      }
      summary = insightSummary;
      health = healthResult;
      maintenanceJobs = (jobsResult?.jobs ?? []).filter((job) => job.kind === 'analytics_refresh' || job.kind === 'base_currency_rebuild');
      updateSettings(settingsResult);
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Settings are temporarily unavailable.';
    } finally {
      loading = false;
    }
  }

  async function saveProfile() {
    if (savingProfile || profile === savedProfile) return;
    savingProfile = true;
    pageError = '';
    try {
      const result = await sendJson<SettingsResponse>('/api/settings', 'PATCH', {
        marketProfile: profile || null
      });
      settings = result;
      savedProfile = result.marketProfile ?? '';
      updateSettings(result);
      message = profile
        ? `${profile === 'CA' ? 'Canada' : 'Tanzania'} is now the default market for first visits and new accounts.`
        : 'The default market was cleared. First visits now open All.';
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The market profile could not be saved.';
    } finally {
      savingProfile = false;
    }
  }

  async function saveSensitivity() {
    if (savingSensitivity || sensitivity === savedSensitivity) return;
    savingSensitivity = true;
    pageError = '';
    try {
      const response = await sendJson<InsightSettingsResponse>('/api/insights/settings', 'PATCH', { sensitivity });
      sensitivity = response.settings.sensitivity;
      savedSensitivity = response.settings.sensitivity;
      message = response.refresh
        ? `Sensitivity saved and a full analytics refresh was queued (${response.refresh.jobId.slice(0, 8)}…).`
        : 'Detection sensitivity saved.';
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Detection sensitivity could not be saved.';
      sensitivity = savedSensitivity;
    } finally {
      savingSensitivity = false;
    }
  }

  async function rebuild() {
    if (rebuilding) return;
    rebuilding = true;
    pageError = '';
    try {
      const accepted = await sendJson<{ jobId: string }>('/api/insights/rebuild', 'POST', { mode: 'full' });
      message = `Full analytics refresh queued (${accepted.jobId.slice(0, 8)}…). Published Insights remain available until the replacement is ready.`;
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The analytics refresh could not be queued.';
    } finally {
      rebuilding = false;
    }
  }

  async function pollCurrencyJob(jobId: string, attempt = 0): Promise<void> {
    if (attempt > 600) {
      switchingCurrency = false;
      message = 'The home-currency rebuild is still running. Its status remains available in Advanced settings.';
      return;
    }
    try {
      const job = await readJson<JobResponse>(`/api/jobs/${jobId}`);
      if (job.status === 'done') {
        switchingCurrency = false;
        currencyConfirmed = false;
        message = `Home currency changed to ${targetCurrency}. Reporting values are rebuilt from native amounts.`;
        await load();
        return;
      }
      if (job.status === 'failed') {
        switchingCurrency = false;
        pageError = job.error || 'The home-currency rebuild failed. Existing reporting values were not relabelled.';
        return;
      }
      pollTimer = setTimeout(() => void pollCurrencyJob(jobId, attempt + 1), 1500);
    } catch (error) {
      switchingCurrency = false;
      pageError = error instanceof Error ? error.message : 'The home-currency job could not be checked.';
    }
  }

  async function switchCurrency() {
    if (switchingCurrency || !currencyConfirmed || !settings || targetCurrency === settings.baseCurrency) return;
    switchingCurrency = true;
    pageError = '';
    try {
      const accepted = await sendJson<{ jobId: string }>('/api/settings/base-currency', 'POST', {
        baseCurrency: targetCurrency,
        confirmed: true
      });
      message = `Rebuilding ${targetCurrency} reporting values and analytics…`;
      await pollCurrencyJob(accepted.jobId);
    } catch (error) {
      switchingCurrency = false;
      pageError = error instanceof Error ? error.message : 'The home-currency change could not be started.';
    }
  }

  onMount(load);
  onDestroy(() => { if (pollTimer) clearTimeout(pollTimer); });
</script>

<svelte:head>
  <title>Settings · Ledger</title>
  <meta name="description" content="Configure Ledger market defaults, reporting currency, and advanced analytics controls." />
</svelte:head>

<div class="page settings-page">
  <header class="page-header">
    <div class="page-header-copy">
      <p class="eyebrow">Preferences and operations</p>
      <h1>Settings, without the clutter.</h1>
      <p class="lede">Regional defaults are separate from consolidated reporting. Operational controls stay here, away from everyday activity.</p>
    </div>
  </header>

  {#if pageError}<div class="status-banner" role="alert"><strong>Settings need attention.</strong><span>{pageError}</span><button class="button-secondary" type="button" on:click={load}>Try again</button></div>{/if}
  {#if message}<div class="status-banner success" role="status"><strong>Updated.</strong><span>{message}</span><button class="text-button" type="button" on:click={() => (message = '')}>Dismiss</button></div>{/if}

  <section class="settings-grid" aria-label="General settings">
    <article class="panel">
      <div class="panel-heading"><div><h2>Market profile</h2><p>Used for first visits and as the default when adding an account. It does not change reporting currency.</p></div></div>
      {#if loading}<div class="skeleton-block"></div>{:else}
        <div class="setting-row">
          <label class="field"><span>Default market</span><select bind:value={profile}><option value="">No default · open All</option><option value="CA">Canada</option><option value="TZ">Tanzania</option></select></label>
          <button class="button" type="button" disabled={savingProfile || profile === savedProfile} on:click={saveProfile}>{savingProfile ? 'Saving…' : 'Save profile'}</button>
        </div>
      {/if}
    </article>

    <article class="panel currency-summary">
      <div class="panel-heading"><div><h2>Home currency</h2><p>The stable consolidated reporting lens. Market scope never changes it.</p></div><span class="currency-chip">{settings?.baseCurrency ?? '—'}</span></div>
      <p>Accounts and transactions always retain their native posted currency. Reporting values are derived and may remain pending when a historical rate is unavailable.</p>
    </article>
  </section>

  <section class="advanced" aria-labelledby="advanced-title">
    <div class="section-title"><p class="eyebrow">Maintenance</p><h2 id="advanced-title">Advanced</h2></div>
    <div class="advanced-grid">
      <article class="panel">
        <div class="panel-heading"><div><h2>Analytics generation</h2><p>Readers see only a completely published generation in the active home currency.</p></div><span class:ready={summary?.latestRun?.status === 'succeeded'} class="status-dot">{summary?.latestRun?.status === 'succeeded' ? 'Up to date' : summary?.latestRun?.status ?? 'Not built'}</span></div>
        <dl><div><dt>Database</dt><dd>{health?.status === 'ready' ? 'Ready' : 'Unavailable'}</dd></div><div><dt>Last completed</dt><dd>{dateTime(summary?.latestRun?.finishedAt)}</dd></div><div><dt>Published findings</dt><dd>{summary?.latestRun?.findingCount ?? '—'}</dd></div></dl>
        {#if maintenanceJobs[0]}<p class="job-status">Latest maintenance job · {maintenanceJobs[0].kind.replaceAll('_', ' ')} · <strong>{maintenanceJobs[0].status}</strong> · {dateTime(maintenanceJobs[0].finishedAt ?? maintenanceJobs[0].createdAt)}</p>{/if}
        <button class="button-secondary full" type="button" disabled={rebuilding} on:click={rebuild}>{rebuilding ? 'Queuing…' : 'Rebuild all analytics'}</button>
      </article>

      <article class="panel">
        <div class="panel-heading"><div><h2>Detection sensitivity</h2><p>Changes queue a full refresh and keep existing published Insights visible until completion.</p></div></div>
        <label class="field"><span>Sensitivity</span><select bind:value={sensitivity}><option value="low">Low · fewer, larger deviations</option><option value="balanced">Balanced · documented defaults</option><option value="high">High · more, smaller deviations</option></select></label>
        <button class="button full" type="button" disabled={savingSensitivity || sensitivity === savedSensitivity} on:click={saveSensitivity}>{savingSensitivity ? 'Saving…' : 'Save sensitivity'}</button>
      </article>

      <article class="panel currency-switch">
        <div class="panel-heading"><div><h2>Change home currency</h2><p>Maintenance action for CAD or TZS reporting. Native values are never rewritten.</p></div></div>
        <label class="field"><span>Target home currency</span><select bind:value={targetCurrency} disabled={loading || switchingCurrency}><option value="CAD">CAD · Canadian dollar</option><option value="TZS">TZS · Tanzanian shilling</option></select></label>
        <label class="confirmation"><input type="checkbox" bind:checked={currencyConfirmed} disabled={switchingCurrency || targetCurrency === settings?.baseCurrency} /><span>I understand Insights will rebuild and may temporarily show a maintenance state.</span></label>
        <button class="button-danger full" type="button" disabled={switchingCurrency || !currencyConfirmed || targetCurrency === settings?.baseCurrency} on:click={switchCurrency}>{switchingCurrency ? 'Rebuilding…' : `Change to ${targetCurrency}`}</button>
      </article>
    </div>
  </section>
</div>

<style>
  .settings-grid { display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 1rem; align-items: stretch; }
  .setting-row { display: grid; grid-template-columns: minmax(180px, 1fr) auto; gap: 0.6rem; align-items: end; }
  .currency-summary > p { margin: 0; color: var(--muted); font-size: 0.7rem; line-height: 1.6; }
  .currency-chip { display: grid; min-width: 52px; height: 34px; padding: 0 0.65rem; place-items: center; color: white; border-radius: 10px; background: var(--forest); font-size: 0.72rem; font-weight: 850; }
  .advanced { display: grid; gap: 0.8rem; }
  .section-title p, .section-title h2 { margin: 0; }
  .section-title h2 { margin-top: 0.2rem; font-size: 1.5rem; letter-spacing: -0.04em; }
  .advanced-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.8rem; align-items: start; }
  .advanced-grid article { display: grid; gap: 0.8rem; }
  .status-dot { padding: 0.28rem 0.5rem; color: #765c19; border-radius: 999px; background: #f5e8bd; font-size: 0.58rem; font-weight: 800; white-space: nowrap; text-transform: capitalize; }
  .status-dot.ready { color: #20624f; background: #dcefe8; }
  dl { margin: 0; }
  dl div { display: flex; min-height: 38px; padding: 0.45rem 0; align-items: center; justify-content: space-between; gap: 1rem; border-top: 1px solid #e5e7e1; }
  dt { color: var(--muted); font-size: 0.64rem; }
  dd { margin: 0; font-size: 0.68rem; font-weight: 800; text-align: right; }
  .full { width: 100%; }
  .job-status { margin: 0; color: var(--muted); font-size: 0.6rem; line-height: 1.5; text-transform: capitalize; }
  .confirmation { display: flex; align-items: flex-start; gap: 0.5rem; color: var(--muted); font-size: 0.64rem; line-height: 1.45; }
  .confirmation input { margin-top: 0.14rem; }
  @media (max-width: 980px) { .advanced-grid { grid-template-columns: 1fr 1fr; } .currency-switch { grid-column: 1 / -1; } }
  @media (max-width: 700px) { .settings-grid, .advanced-grid, .setting-row { grid-template-columns: 1fr; } .currency-switch { grid-column: auto; } }
</style>
