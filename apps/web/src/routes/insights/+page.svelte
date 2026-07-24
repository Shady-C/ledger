<script lang="ts">
  import { onMount } from 'svelte';
  import type {
    AccountsResponse,
    CategoriesResponse,
    InsightDimension,
    InsightFinding,
    InsightFindingSeverity,
    InsightFindingStatus,
    InsightFindingType,
    InsightFindingsResponse,
    InsightRange,
    InsightRecurringResponse,
    InsightSeasonalityResponse,
    InsightSensitivity,
    InsightSettingsResponse,
    InsightSummaryResponse,
    InsightTrendsResponse,
    RecurringCadence,
    RecurringSeries,
    RecurringStatus
  } from '@ledger/shared-types';

  import FindingEvidence from '$lib/components/insights/FindingEvidence.svelte';
  import TrendChart from '$lib/components/insights/TrendChart.svelte';
  import { dateTime, readJson, sendJson } from '$lib/components/api-client.js';
  import { money, shortDate } from '$lib/format.js';

  type Tab = 'overview' | 'trends' | 'recurring' | 'findings';
  type RecurringDraft = { cadence: RecurringCadence; expectedAmount: string };

  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'trends', label: 'Trends' },
    { id: 'recurring', label: 'Recurring' },
    { id: 'findings', label: 'Findings' }
  ];
  const findingTypes: InsightFindingType[] = [
    'unusual_amount',
    'unusual_frequency',
    'monthly_spike',
    'near_duplicate',
    'recurring_price_increase',
    'recurring_overdue',
    'reconciliation_mismatch',
    'coverage_gap',
    'pending_fx'
  ];
  const recurringCadences: RecurringCadence[] = [
    'weekly',
    'biweekly',
    'monthly',
    'quarterly',
    'annual'
  ];

  let activeTab: Tab = 'overview';
  let range: InsightRange = '12m';
  let accounts: AccountsResponse['accounts'] = [];
  let categories: CategoriesResponse['categories'] = [];
  let merchantOptions: { id: string; name: string }[] = [];
  let accountId = '';
  let categoryId = '';
  let merchantId = '';
  let trendGroupBy: InsightDimension = 'ledger';
  let summary: InsightSummaryResponse | null = null;
  let trends: InsightTrendsResponse | null = null;
  let seasonality: InsightSeasonalityResponse | null = null;
  let recurring: InsightRecurringResponse | null = null;
  let findings: InsightFindingsResponse | null = null;
  let sensitivity: InsightSensitivity = 'balanced';
  let savedSensitivity: InsightSensitivity = 'balanced';
  let recurringStatus: RecurringStatus | '' = '';
  let recurringCadence: RecurringCadence | '' = '';
  let findingStatus: InsightFindingStatus | '' = '';
  let findingSeverity: InsightFindingSeverity | '' = '';
  let findingType: InsightFindingType | '' = '';
  let recurringPage = 1;
  let findingsPage = 1;
  let recurringDrafts: Record<string, RecurringDraft> = {};
  let loading = true;
  let refreshingTrends = false;
  let pageError = '';
  let message = '';
  let actionId = '';
  let savingSettings = false;
  let rebuilding = false;

  $: ledgerTrendPoints = trends?.points.filter((point) => point.dimensionType === 'ledger') ?? [];
  $: displayedTrendPoints = trendGroupBy === 'ledger' ? ledgerTrendPoints : trends?.points ?? [];

  function queryString(extra: Record<string, string | number | undefined> = {}) {
    const params = new URLSearchParams({ range });
    if (accountId) params.set('accountId', accountId);
    if (categoryId) params.set('categoryId', categoryId);
    if (merchantId) params.set('merchantId', merchantId);
    for (const [key, value] of Object.entries(extra)) {
      if (value !== '' && value !== undefined) params.set(key, String(value));
    }
    return params.toString();
  }

  function syncMerchantOptions(
    seriesItems: RecurringSeries[],
    findingItems: InsightFinding[],
    trendPoints: InsightTrendsResponse['points'] = []
  ) {
    const options = new Map(merchantOptions.map((option) => [option.id, option.name]));
    for (const series of seriesItems) {
      if (series.merchantId) options.set(series.merchantId, series.merchantName);
    }
    for (const finding of findingItems) {
      if (finding.merchantId && finding.merchantName) {
        options.set(finding.merchantId, finding.merchantName);
      }
    }
    for (const point of trendPoints) {
      if (point.dimensionType === 'merchant' && point.dimensionId) {
        options.set(point.dimensionId, point.dimensionName);
      }
    }
    merchantOptions = [...options.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((left, right) => left.name.localeCompare(right.name));
  }

  async function applyEntityFilter(kind: 'account' | 'category' | 'merchant') {
    if (kind !== 'account') accountId = '';
    if (kind !== 'category') categoryId = '';
    if (kind !== 'merchant') merchantId = '';
    trendGroupBy = accountId || categoryId || merchantId ? kind : 'ledger';
    recurringPage = 1;
    findingsPage = 1;
    await load();
  }

  async function load() {
    loading = true;
    pageError = '';
    try {
      const [summaryResult, trendsResult, seasonalityResult, recurringResult, findingsResult, settingsResult, accountResult, categoryResult] = await Promise.all([
        readJson<InsightSummaryResponse>(`/api/insights/summary?${queryString()}`),
        readJson<InsightTrendsResponse>(`/api/insights/trends?${queryString({ groupBy: trendGroupBy })}`),
        readJson<InsightSeasonalityResponse>(`/api/insights/seasonality?${queryString()}`),
        readJson<InsightRecurringResponse>(`/api/insights/recurring?${queryString({ page: recurringPage, status: recurringStatus || undefined, cadence: recurringCadence || undefined })}`),
        readJson<InsightFindingsResponse>(`/api/insights/findings?${queryString({ page: findingsPage, status: findingStatus || undefined, severity: findingSeverity || undefined, type: findingType || undefined })}`),
        readJson<InsightSettingsResponse>('/api/insights/settings'),
        readJson<AccountsResponse>('/api/accounts'),
        readJson<CategoriesResponse>('/api/categories')
      ]);
      summary = summaryResult;
      trends = trendsResult;
      seasonality = seasonalityResult;
      recurring = recurringResult;
      findings = findingsResult;
      sensitivity = settingsResult.settings.sensitivity;
      savedSensitivity = settingsResult.settings.sensitivity;
      accounts = accountResult.accounts;
      categories = categoryResult.categories;
      syncMerchantOptions(recurringResult.series, findingsResult.findings, trendsResult.points);
      syncRecurringDrafts(recurringResult.series);
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Insights are temporarily unavailable.';
    } finally {
      loading = false;
    }
  }

  async function loadTrends() {
    refreshingTrends = true;
    pageError = '';
    try {
      trends = await readJson<InsightTrendsResponse>(
        `/api/insights/trends?${queryString({ groupBy: trendGroupBy })}`
      );
      if (trends) syncMerchantOptions(
        recurring?.series ?? [],
        findings?.findings ?? [],
        trends.points
      );
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Trend data could not be loaded.';
    } finally {
      refreshingTrends = false;
    }
  }

  async function loadRecurring() {
    try {
      recurring = await readJson<InsightRecurringResponse>(
        `/api/insights/recurring?${queryString({ page: recurringPage, status: recurringStatus || undefined, cadence: recurringCadence || undefined })}`
      );
      syncRecurringDrafts(recurring.series);
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Recurring series could not be loaded.';
    }
  }

  async function loadFindings() {
    try {
      findings = await readJson<InsightFindingsResponse>(
        `/api/insights/findings?${queryString({ page: findingsPage, status: findingStatus || undefined, severity: findingSeverity || undefined, type: findingType || undefined })}`
      );
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Findings could not be loaded.';
    }
  }

  function syncRecurringDrafts(series: RecurringSeries[]) {
    recurringDrafts = Object.fromEntries(
      series.map((item) => [item.id, { cadence: item.cadence, expectedAmount: item.expectedAmount }])
    );
  }

  async function updateRecurring(
    series: RecurringSeries,
    patch: { status?: Exclude<RecurringStatus, 'detected'>; cadence?: RecurringCadence; expectedAmount?: string }
  ) {
    actionId = series.id;
    pageError = '';
    try {
      await sendJson(`/api/insights/recurring/${series.id}`, 'PATCH', patch);
      message = `${series.merchantName} was updated.`;
      await Promise.all([loadRecurring(), reloadSummary()]);
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The recurring series could not be updated.';
    } finally {
      actionId = '';
    }
  }

  async function saveRecurringCorrection(series: RecurringSeries) {
    const draft = recurringDrafts[series.id];
    if (!draft) return;
    await updateRecurring(series, draft);
  }

  async function reviewFinding(finding: InsightFinding, status: 'confirmed' | 'dismissed' | 'resolved') {
    actionId = finding.id;
    pageError = '';
    try {
      await sendJson(`/api/insights/findings/${finding.id}`, 'PATCH', { status });
      message = `Finding ${status}.`;
      await Promise.all([loadFindings(), reloadSummary()]);
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The finding could not be reviewed.';
    } finally {
      actionId = '';
    }
  }

  async function reloadSummary() {
    summary = await readJson<InsightSummaryResponse>(`/api/insights/summary?${queryString()}`);
  }

  async function saveSensitivity() {
    if (sensitivity === savedSensitivity || savingSettings) return;
    savingSettings = true;
    pageError = '';
    try {
      const response = await sendJson<InsightSettingsResponse>('/api/insights/settings', 'PATCH', {
        sensitivity
      });
      sensitivity = response.settings.sensitivity;
      savedSensitivity = response.settings.sensitivity;
      message = response.refresh
        ? `Insight sensitivity was saved and a full refresh was queued (${response.refresh.jobId.slice(0, 8)}…).`
        : 'Insight sensitivity was saved.';
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Sensitivity could not be saved.';
      sensitivity = savedSensitivity;
    } finally {
      savingSettings = false;
    }
  }

  async function rebuild() {
    if (rebuilding) return;
    rebuilding = true;
    pageError = '';
    try {
      const accepted = await sendJson<{ jobId: string }>('/api/insights/rebuild', 'POST', { mode: 'full' });
      message = `Full analytics refresh queued (${accepted.jobId.slice(0, 8)}…). Existing published Insights remain visible while it runs.`;
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The analytics refresh could not be queued.';
    } finally {
      rebuilding = false;
    }
  }

  function activateTab(tab: Tab) {
    activeTab = tab;
  }

  function tabKeydown(event: KeyboardEvent, index: number) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    let next = index;
    if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    const tab = tabs[next]!;
    activeTab = tab.id;
    requestAnimationFrame(() => document.getElementById(`insights-tab-${tab.id}`)?.focus());
  }

  function label(value: string) {
    return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
  }

  function signedPercent(value: string | null) {
    if (value === null) return 'No prior comparison';
    const amount = Number(value);
    if (!Number.isFinite(amount)) return 'Not available';
    return `${amount > 0 ? '+' : ''}${amount.toFixed(1)}%`;
  }

  function runStatus(value: string) {
    return value === 'succeeded' ? 'Up to date' : label(value);
  }

  onMount(load);
</script>

<svelte:head>
  <title>Insights · Ledger</title>
  <meta name="description" content="Explore deterministic spending trends, recurring activity, seasonality, and reviewable financial findings." />
</svelte:head>

<div class="page insights-page">
  <header class="page-header">
    <div class="page-header-copy">
      <p class="eyebrow">Deterministic analytics</p>
      <h1>See the pattern. Inspect the proof.</h1>
      <p class="lede">Trends, recurring activity, and unusual events are calculated from your ledger. Every finding keeps its evidence and review state.</p>
    </div>
    <div class="header-controls">
      <label class="field compact-field">
        <span>History</span>
        <select bind:value={range} on:change={() => { recurringPage = 1; findingsPage = 1; void load(); }}>
          <option value="3m">Last 3 months</option>
          <option value="6m">Last 6 months</option>
          <option value="12m">Last 12 months</option>
          <option value="24m">Last 24 months</option>
          <option value="all">All history</option>
        </select>
      </label>
      <label class="field compact-field">
        <span>Account</span>
        <select bind:value={accountId} on:change={() => void applyEntityFilter('account')}>
          <option value="">All accounts</option>
          {#each accounts as account}<option value={account.id}>{account.displayName}</option>{/each}
        </select>
      </label>
      <label class="field compact-field">
        <span>Category</span>
        <select bind:value={categoryId} on:change={() => void applyEntityFilter('category')}>
          <option value="">All categories</option>
          {#each categories as category}<option value={category.id}>{category.name}</option>{/each}
        </select>
      </label>
      <label class="field compact-field">
        <span>Merchant</span>
        <select bind:value={merchantId} on:change={() => void applyEntityFilter('merchant')}>
          <option value="">All insight merchants</option>
          {#each merchantOptions as merchant}<option value={merchant.id}>{merchant.name}</option>{/each}
        </select>
      </label>
      <button class="button-secondary" type="button" disabled={rebuilding} on:click={rebuild}>{rebuilding ? 'Queuing…' : 'Rebuild insights'}</button>
    </div>
  </header>

  {#if pageError}
    <div class="status-banner" role="alert"><strong>Insights need attention.</strong><span>{pageError}</span><button class="button-secondary" type="button" on:click={load}>Try again</button></div>
  {:else if message}
    <div class="status-banner success" role="status"><strong>Updated.</strong><span>{message}</span><button class="text-button" type="button" on:click={() => (message = '')}>Dismiss</button></div>
  {/if}

  {#if summary?.coverage.status === 'partial'}
    <div class="status-banner info" role="status">
      <strong>CAD totals are partial.</strong>
      <span>{summary.coverage.unvaluedTransactionCount} transaction{summary.coverage.unvaluedTransactionCount === 1 ? '' : 's'} await CAD valuation and are excluded from consolidated totals.</span>
    </div>
  {/if}

  <div class="insights-tabs" role="tablist" aria-label="Insights views">
    {#each tabs as tab, index}
      <button
        id={`insights-tab-${tab.id}`}
        role="tab"
        type="button"
        aria-selected={activeTab === tab.id}
        aria-controls={`insights-panel-${tab.id}`}
        tabindex={activeTab === tab.id ? 0 : -1}
        class:active={activeTab === tab.id}
        on:click={() => activateTab(tab.id)}
        on:keydown={(event) => tabKeydown(event, index)}
      >
        {tab.label}
        {#if tab.id === 'findings' && summary?.findings.unread}<span>{summary.findings.unread}</span>{/if}
      </button>
    {/each}
  </div>

  {#if loading}
    <div class="loading-grid" aria-label="Loading Insights"><div class="skeleton-block"></div><div class="skeleton-block"></div><div class="skeleton-block"></div></div>
  {:else if activeTab === 'overview'}
    <div id="insights-panel-overview" role="tabpanel" aria-labelledby="insights-tab-overview" class="tab-panel">
      <div class="metric-grid">
        <article class="metric-card"><span>Spending</span><strong>{money(summary?.totals.spending ?? '0', 'CAD')}</strong><small>{summary?.spendingMonthOverMonth ? `${signedPercent(summary.spendingMonthOverMonth.changePercent)} vs prior month` : 'No prior month comparison'}</small></article>
        <article class="metric-card"><span>Inflow</span><strong>{money(summary?.totals.inflow ?? '0', 'CAD')}</strong><small>Valued activity in this range</small></article>
        <article class="metric-card"><span>Net cash flow</span><strong class:negative={Number(summary?.totals.netCashflow ?? '0') < 0}>{money(summary?.totals.netCashflow ?? '0', 'CAD')}</strong><small>{summary?.spendingYearOverYear ? `${signedPercent(summary.spendingYearOverYear.changePercent)} spending vs last year` : 'Year-over-year pending history'}</small></article>
        <article class="metric-card accent"><span>Needs review</span><strong>{summary?.findings.unread ?? 0}</strong><small>{summary?.findings.confirmed ?? 0} confirmed · {summary?.findings.dismissed ?? 0} dismissed</small></article>
      </div>

      <div class="overview-grid">
        <article class="panel trend-panel">
          <div class="panel-heading"><div><h2>Monthly spending</h2><p>CAD-valued spending with partial months clearly marked.</p></div><button class="text-button" type="button" on:click={() => (activeTab = 'trends')}>Explore trends</button></div>
          <TrendChart points={ledgerTrendPoints} currency="CAD" />
        </article>
        <div class="side-stack">
          <article class="panel summary-card">
            <div class="panel-heading"><div><h2>Recurring activity</h2><p>Expected dates are recurrence metadata, not a cash-flow forecast.</p></div></div>
            <dl><div><dt>Active series</dt><dd>{summary?.recurring.activeSeries ?? 0}</dd></div><div><dt>Overdue</dt><dd>{summary?.recurring.overdueSeries ?? 0}</dd></div><div><dt>Monthly equivalent</dt><dd>{money(summary?.recurring.expectedMonthlyAmount ?? '0', 'CAD')}</dd></div></dl>
            <button class="button-secondary full-button" type="button" on:click={() => (activeTab = 'recurring')}>Review recurring activity</button>
          </article>
          <article class="panel summary-card">
            <div class="panel-heading"><div><h2>Analytics health</h2><p>Readers always see the last completely published generation.</p></div></div>
            {#if summary?.latestRun}
              <dl><div><dt>Status</dt><dd>{runStatus(summary.latestRun.status)}</dd></div><div><dt>Mode</dt><dd>{label(summary.latestRun.mode)}</dd></div><div><dt>Finished</dt><dd>{dateTime(summary.latestRun.finishedAt)}</dd></div><div><dt>Findings</dt><dd>{summary.latestRun.findingCount}</dd></div></dl>
            {:else}
              <p class="muted-copy">No analytics refresh has completed yet.</p>
            {/if}
          </article>
        </div>
      </div>

      <article class="panel settings-panel">
        <div class="panel-heading"><div><h2>Detection sensitivity</h2><p>Balanced uses the documented materiality and robust-statistics defaults. Saving automatically queues a full refresh.</p></div></div>
        <div class="settings-row"><label class="field"><span>Sensitivity</span><select bind:value={sensitivity}><option value="low">Low · fewer, larger deviations</option><option value="balanced">Balanced · recommended defaults</option><option value="high">High · more, smaller deviations</option></select></label><button class="button" type="button" disabled={sensitivity === savedSensitivity || savingSettings} on:click={saveSensitivity}>{savingSettings ? 'Saving…' : 'Save sensitivity'}</button></div>
      </article>
    </div>
  {:else if activeTab === 'trends'}
    <div id="insights-panel-trends" role="tabpanel" aria-labelledby="insights-tab-trends" class="tab-panel">
      <article class="panel">
        <div class="panel-heading trends-heading"><div><h2>Monthly movement</h2><p>Choose a ledger total or break activity down by account, category, or merchant.</p></div><label class="field compact-field"><span>Break down by</span><select bind:value={trendGroupBy} disabled={Boolean(accountId || categoryId || merchantId)} on:change={loadTrends}><option value="ledger">Ledger total</option><option value="category">Category</option><option value="merchant">Merchant</option><option value="account">Account</option></select></label></div>
        {#if refreshingTrends}<div class="skeleton-block"></div>{:else if trendGroupBy === 'ledger'}<TrendChart points={displayedTrendPoints} currency="CAD" />{/if}
        {#if trendGroupBy !== 'ledger'}
          <div class="table-scroll"><table><thead><tr><th>Month</th><th>{label(trendGroupBy)}</th><th>Spending</th><th>MoM</th><th>YoY</th><th>Inflow</th><th>Net cash flow</th><th>Coverage</th></tr></thead><tbody>{#each displayedTrendPoints as point}<tr><td>{shortDate(point.period)}</td><td>{point.dimensionName}</td><td>{money(point.spending, 'CAD')}</td><td>{signedPercent(point.monthOverMonth?.changePercent ?? null)}</td><td>{signedPercent(point.yearOverYear?.changePercent ?? null)}</td><td>{money(point.inflow, 'CAD')}</td><td>{money(point.netCashflow, 'CAD')}</td><td><span class:partial-pill={point.coverageStatus === 'partial'} class="pill">{label(point.coverageStatus)}</span></td></tr>{/each}</tbody></table></div>
        {/if}
      </article>

      <div class="trend-details-grid">
        <article class="panel">
          <div class="panel-heading"><div><h2>Largest movers</h2><p>Current complete month compared with the previous complete month.</p></div></div>
          {#if (trends?.movers.positive.length ?? 0) + (trends?.movers.negative.length ?? 0) === 0}
            <div class="empty-state"><strong>No comparable movers</strong><p>Two complete months are needed.</p></div>
          {:else}
            <ul class="mover-list">{#each [...(trends?.movers.positive ?? []), ...(trends?.movers.negative ?? [])] as mover}<li><span><strong>{mover.dimensionName}</strong><small>{label(mover.dimensionType)}</small></span><span class:negative={Number(mover.changeAmount) < 0}>{signedPercent(mover.changePercent)}<small>{money(mover.changeAmount, 'CAD')}</small></span></li>{/each}</ul>
          {/if}
        </article>
        <article class="panel">
          <div class="panel-heading"><div><h2>Month-of-year seasonality</h2><p>Shown only after at least 12 months of history.</p></div></div>
          {#if seasonality?.status === 'insufficient_history'}
            <div class="empty-state"><strong>More history needed</strong><p>{seasonality.historyMonths} of {seasonality.requiredHistoryMonths} required months are available.</p></div>
          {:else}
            <div class="seasonality-grid">{#each seasonality?.months ?? [] as month}<div><span>{month.monthName}</span><strong>{money(month.averageSpending, 'CAD')}</strong><small>{month.observationCount} observation{month.observationCount === 1 ? '' : 's'} · median {money(month.medianSpending, 'CAD')}</small></div>{/each}</div>
          {/if}
        </article>
      </div>
    </div>
  {:else if activeTab === 'recurring'}
    <div id="insights-panel-recurring" role="tabpanel" aria-labelledby="insights-tab-recurring" class="tab-panel">
      <div class="filter-bar panel"><div><h2>Recurring activity</h2><p>Confirm detections, correct cadence or amount, and retire cancelled patterns.</p></div><label class="field compact-field"><span>Status</span><select bind:value={recurringStatus} on:change={() => { recurringPage = 1; void loadRecurring(); }}><option value="">All statuses</option><option value="detected">Detected</option><option value="confirmed">Confirmed</option><option value="cancelled">Cancelled</option><option value="ignored">Ignored</option></select></label><label class="field compact-field"><span>Cadence</span><select bind:value={recurringCadence} on:change={() => { recurringPage = 1; void loadRecurring(); }}><option value="">All cadences</option>{#each recurringCadences as cadence}<option value={cadence}>{label(cadence)}</option>{/each}</select></label></div>
      {#if recurring?.series.length === 0}
        <div class="panel empty-state"><strong>No recurring series match</strong><p>Series appear after at least three stable occurrences, or two for annual activity.</p></div>
      {:else}
        <div class="recurring-grid">
          {#each recurring?.series ?? [] as series}
            <article class="panel recurring-card">
              <div class="card-heading"><div><div class="pill-row"><span class="pill">{label(series.status)}</span><span class="pill">{label(series.cadence)}</span>{#if series.overdue}<span class="pill attention">Overdue</span>{/if}</div><h3>{series.merchantName}</h3><p>{series.direction === 'spend' ? 'Recurring spend' : 'Recurring income'} · {series.occurrenceCount} occurrences</p></div><strong>{money(series.expectedAmount, series.currency)}</strong></div>
              <dl class="series-facts"><div><dt>Comparison basis</dt><dd>{label(series.comparisonBasis)} · {series.currency}</dd></div><div><dt>Last seen</dt><dd>{shortDate(series.lastOccurrenceDate)}</dd></div><div><dt>Expected next</dt><dd>{series.expectedNextDate ? shortDate(series.expectedNextDate) : 'Not available'}</dd></div><div><dt>Latest change</dt><dd>{signedPercent(series.latestChangePercent)}</dd></div></dl>
              <details><summary>Occurrence history</summary><ol class="occurrence-list">{#each series.occurrences as occurrence}<li><span>{shortDate(occurrence.bookedDate)}</span><strong>{money(occurrence.amount, occurrence.currency)}</strong></li>{/each}</ol></details>
              <form class="correction-form" on:submit|preventDefault={() => saveRecurringCorrection(series)}>
                <label class="field"><span>Expected cadence</span><select value={recurringDrafts[series.id]?.cadence ?? series.cadence} on:change={(event) => { const target = event.currentTarget as HTMLSelectElement; recurringDrafts = { ...recurringDrafts, [series.id]: { ...(recurringDrafts[series.id] ?? { expectedAmount: series.expectedAmount }), cadence: target.value as RecurringCadence } }; }}>{#each recurringCadences as cadence}<option value={cadence}>{label(cadence)}</option>{/each}</select></label>
                <label class="field"><span>Expected amount ({series.currency})</span><input inputmode="decimal" value={recurringDrafts[series.id]?.expectedAmount ?? series.expectedAmount} on:input={(event) => { const target = event.currentTarget as HTMLInputElement; recurringDrafts = { ...recurringDrafts, [series.id]: { ...(recurringDrafts[series.id] ?? { cadence: series.cadence }), expectedAmount: target.value } }; }} /></label>
                <button class="button-secondary" type="submit" disabled={actionId === series.id}>Save correction</button>
              </form>
              <div class="review-actions">{#if series.status !== 'confirmed'}<button class="button" type="button" disabled={actionId === series.id} on:click={() => updateRecurring(series, { status: 'confirmed' })}>Confirm</button>{/if}{#if series.status !== 'ignored'}<button class="button-secondary" type="button" disabled={actionId === series.id} on:click={() => updateRecurring(series, { status: 'ignored' })}>Ignore</button>{/if}{#if series.status !== 'cancelled'}<button class="text-button" type="button" disabled={actionId === series.id} on:click={() => updateRecurring(series, { status: 'cancelled' })}>Mark cancelled</button>{/if}</div>
            </article>
          {/each}
        </div>
      {/if}
      {#if recurring && recurring.totalPages > 1}<nav class="pagination" aria-label="Recurring pages"><button class="button-secondary" type="button" disabled={recurringPage <= 1} on:click={() => { recurringPage -= 1; void loadRecurring(); }}>Previous</button><span>Page {recurring.page} of {recurring.totalPages}</span><button class="button-secondary" type="button" disabled={recurringPage >= recurring.totalPages} on:click={() => { recurringPage += 1; void loadRecurring(); }}>Next</button></nav>{/if}
    </div>
  {:else}
    <div id="insights-panel-findings" role="tabpanel" aria-labelledby="insights-tab-findings" class="tab-panel">
      <div class="filter-bar panel"><div><h2>Reviewable findings</h2><p>Nothing is silently deleted: findings keep their evidence and review history.</p></div><label class="field compact-field"><span>Status</span><select bind:value={findingStatus} on:change={() => { findingsPage = 1; void loadFindings(); }}><option value="">All statuses</option><option value="new">New</option><option value="confirmed">Confirmed</option><option value="dismissed">Dismissed</option><option value="resolved">Resolved</option></select></label><label class="field compact-field"><span>Severity</span><select bind:value={findingSeverity} on:change={() => { findingsPage = 1; void loadFindings(); }}><option value="">All severity</option><option value="info">Info</option><option value="warning">Warning</option><option value="critical">Critical</option></select></label><label class="field compact-field"><span>Type</span><select bind:value={findingType} on:change={() => { findingsPage = 1; void loadFindings(); }}><option value="">All finding types</option>{#each findingTypes as type}<option value={type}>{label(type)}</option>{/each}</select></label></div>
      {#if findings?.findings.length === 0}
        <div class="panel empty-state"><strong>No findings match</strong><p>Try a different status, severity, type, or history range.</p></div>
      {:else}
        <div class="finding-list">
          {#each findings?.findings ?? [] as finding}
            <article class="panel finding-card">
              <div class="finding-heading"><div><div class="pill-row"><span class={`pill severity-${finding.severity}`}>{label(finding.severity)}</span><span class="pill">{label(finding.type)}</span><span class="pill">{label(finding.status)}</span></div><h3>{finding.title}</h3><p>{finding.summary}</p></div><small>Last seen {dateTime(finding.lastSeenAt)}</small></div>
              <div class="finding-context">{#if finding.accountName}<span>Account <strong>{finding.accountName}</strong></span>{/if}{#if finding.merchantName}<span>Merchant <strong>{finding.merchantName}</strong></span>{/if}{#if finding.categoryName}<span>Category <strong>{finding.categoryName}</strong></span>{/if}</div>
              <details class="evidence"><summary>Calculation and evidence</summary><FindingEvidence evidence={finding.evidence} /></details>
              {#if finding.status !== 'resolved'}<div class="review-actions">{#if finding.status !== 'confirmed'}<button class="button" type="button" disabled={actionId === finding.id} on:click={() => reviewFinding(finding, 'confirmed')}>Confirm finding</button>{/if}{#if finding.status !== 'dismissed'}<button class="button-secondary" type="button" disabled={actionId === finding.id} on:click={() => reviewFinding(finding, 'dismissed')}>Dismiss</button>{/if}{#if finding.status !== 'new'}<button class="text-button" type="button" disabled={actionId === finding.id} on:click={() => reviewFinding(finding, 'resolved')}>Mark resolved</button>{/if}</div>{/if}
            </article>
          {/each}
        </div>
      {/if}
      {#if findings && findings.totalPages > 1}<nav class="pagination" aria-label="Finding pages"><button class="button-secondary" type="button" disabled={findingsPage <= 1} on:click={() => { findingsPage -= 1; void loadFindings(); }}>Previous</button><span>Page {findings.page} of {findings.totalPages}</span><button class="button-secondary" type="button" disabled={findingsPage >= findings.totalPages} on:click={() => { findingsPage += 1; void loadFindings(); }}>Next</button></nav>{/if}
    </div>
  {/if}
</div>

<style>
  .insights-page { --insight-blue: #315f72; }
  .header-controls { display: flex; align-items: end; justify-content: flex-end; flex-wrap: wrap; gap: 0.6rem; }
  .compact-field { min-width: 138px; }
  .insights-tabs { display: flex; width: fit-content; max-width: 100%; padding: 0.28rem; gap: 0.2rem; overflow-x: auto; border: 1px solid var(--line); border-radius: 13px; background: rgb(252 251 247 / 74%); }
  .insights-tabs button { display: inline-flex; min-height: 42px; padding: 0.55rem 0.88rem; align-items: center; gap: 0.4rem; color: var(--muted); border: 0; border-radius: 9px; background: transparent; font-size: 0.72rem; font-weight: 800; white-space: nowrap; }
  .insights-tabs button.active { color: white; background: var(--forest); }
  .insights-tabs button span { display: grid; min-width: 20px; height: 20px; padding: 0 0.3rem; place-items: center; color: var(--forest); border-radius: 999px; background: var(--mint); font-size: 0.58rem; }
  .tab-panel { display: grid; gap: 1rem; }
  .loading-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 1rem; }
  .loading-grid > :first-child { grid-row: span 2; min-height: 380px; }
  .metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.75rem; }
  .metric-card { display: grid; min-height: 144px; padding: 1rem; align-content: space-between; border: 1px solid var(--line); border-radius: 17px; background: var(--paper); box-shadow: var(--shadow); }
  .metric-card.accent { color: white; border-color: var(--forest-mid); background: var(--forest-mid); }
  .metric-card > span { color: var(--muted); font-size: 0.66rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.08em; }
  .metric-card.accent > span, .metric-card.accent small { color: #bdd2cc; }
  .metric-card strong { color: var(--forest); font-size: clamp(1.35rem, 3vw, 2rem); letter-spacing: -0.055em; font-variant-numeric: tabular-nums; }
  .metric-card.accent strong { color: white; }
  .metric-card small { color: var(--muted); font-size: 0.62rem; line-height: 1.4; }
  .negative { color: var(--danger) !important; }
  .overview-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(280px, 0.65fr); gap: 1rem; align-items: start; }
  .side-stack { display: grid; gap: 1rem; }
  .summary-card dl, .series-facts { display: grid; gap: 0; margin: 0; }
  .summary-card dl > div, .series-facts > div { display: flex; min-height: 38px; padding: 0.45rem 0; align-items: center; justify-content: space-between; gap: 1rem; border-top: 1px solid #e5e7e1; }
  dt { color: var(--muted); font-size: 0.65rem; }
  dd { margin: 0; font-size: 0.68rem; font-weight: 800; text-align: right; }
  .full-button { width: 100%; margin-top: 1rem; }
  .muted-copy { margin: 0; color: var(--muted); font-size: 0.72rem; }
  .settings-row { display: grid; grid-template-columns: minmax(220px, 430px) auto; gap: 0.6rem; align-items: end; }
  .trends-heading { align-items: end; }
  .trend-details-grid { display: grid; grid-template-columns: 0.8fr 1.2fr; gap: 1rem; align-items: start; }
  .table-scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.68rem; }
  th, td { padding: 0.7rem 0.6rem; border-bottom: 1px solid #e5e7e1; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-size: 0.6rem; letter-spacing: 0.07em; text-transform: uppercase; }
  td { font-variant-numeric: tabular-nums; }
  .partial-pill { color: #765c19; background: #f5e8bd; }
  .mover-list, .occurrence-list { padding: 0; margin: 0; list-style: none; }
  .mover-list li, .occurrence-list li { display: flex; min-height: 52px; padding: 0.55rem 0; align-items: center; justify-content: space-between; gap: 1rem; border-top: 1px solid #e5e7e1; }
  .mover-list li > span { display: grid; gap: 0.15rem; text-align: right; font-size: 0.72rem; font-weight: 800; }
  .mover-list li > span:first-child { text-align: left; }
  .mover-list small, .occurrence-list span { color: var(--muted); font-size: 0.62rem; font-weight: 600; }
  .seasonality-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.55rem; }
  .seasonality-grid > div { display: grid; min-height: 98px; padding: 0.7rem; align-content: space-between; gap: 0.25rem; border: 1px solid #e1e3dc; border-radius: 11px; background: #f8f7f2; }
  .seasonality-grid span, .seasonality-grid small { color: var(--muted); font-size: 0.58rem; }
  .seasonality-grid strong { font-size: 0.78rem; }
  .filter-bar { display: grid; grid-template-columns: minmax(220px, 1fr) repeat(3, minmax(130px, auto)); align-items: end; gap: 0.7rem; }
  .filter-bar h2, .filter-bar p { margin: 0; }
  .filter-bar h2 { font-size: 1.25rem; letter-spacing: -0.035em; }
  .filter-bar p { margin-top: 0.25rem; color: var(--muted); font-size: 0.68rem; line-height: 1.4; }
  .recurring-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; align-items: start; }
  .recurring-card, .finding-card { display: grid; gap: 1rem; }
  .card-heading, .finding-heading { display: flex; align-items: start; justify-content: space-between; gap: 1rem; }
  .card-heading h3, .card-heading p, .finding-heading h3, .finding-heading p { margin: 0; }
  .card-heading h3, .finding-heading h3 { margin-top: 0.55rem; font-size: 1rem; letter-spacing: -0.025em; }
  .card-heading p, .finding-heading p { margin-top: 0.25rem; color: var(--muted); font-size: 0.67rem; line-height: 1.5; }
  .card-heading > strong { color: var(--forest); font-size: 1.15rem; white-space: nowrap; }
  .pill-row { display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .pill.attention, .severity-warning { color: #7c5418; background: #f5e4b7; }
  .severity-critical { color: #7f3428; background: #f5d2c8; }
  .severity-info { color: #285863; background: #dcecee; }
  details { border-top: 1px solid #e5e7e1; }
  summary { padding: 0.7rem 0; color: var(--forest); font-size: 0.68rem; font-weight: 800; cursor: pointer; }
  .occurrence-list { max-height: 190px; overflow-y: auto; }
  .correction-form { display: grid; grid-template-columns: 1fr 1fr auto; align-items: end; gap: 0.5rem; }
  .review-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 0.45rem; }
  .finding-list { display: grid; gap: 0.75rem; }
  .finding-heading > div { max-width: 760px; }
  .finding-heading > small { color: var(--muted); font-size: 0.62rem; white-space: nowrap; }
  .finding-context { display: flex; flex-wrap: wrap; gap: 0.45rem 1rem; color: var(--muted); font-size: 0.65rem; }
  .finding-context strong { color: var(--ink); }
  .evidence { padding: 0 0.8rem 0.8rem; border: 1px solid #e1e3dc; border-radius: 11px; background: #f8f7f2; }
  .pagination { display: flex; align-items: center; justify-content: center; gap: 0.8rem; color: var(--muted); font-size: 0.68rem; }
  @media (max-width: 980px) {
    .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .overview-grid, .trend-details-grid { grid-template-columns: 1fr; }
    .filter-bar { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .filter-bar > div { grid-column: 1 / -1; }
    .recurring-grid { grid-template-columns: 1fr; }
  }
  @media (max-width: 700px) {
    .header-controls { width: 100%; align-items: stretch; flex-direction: column; }
    .settings-row, .correction-form { grid-template-columns: 1fr; }
    .seasonality-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .filter-bar { grid-template-columns: 1fr; }
    .filter-bar > div { grid-column: auto; }
    .card-heading, .finding-heading { display: grid; }
    .finding-heading > small { white-space: normal; }
  }
  @media (max-width: 480px) {
    .metric-grid { grid-template-columns: 1fr; }
    .seasonality-grid { grid-template-columns: 1fr; }
  }
</style>
