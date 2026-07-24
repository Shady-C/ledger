<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import type {
    AccountsResponse,
    InstitutionsResponse,
    JobResponse,
    SettingsResponse
  } from '@ledger/shared-types';

  import AccountForm from '$lib/components/AccountForm.svelte';
  import UtilizationMeter from '$lib/components/UtilizationMeter.svelte';
  import { readJson, readOptionalJson, sendJson } from '$lib/components/api-client.js';
  import type { AccountView, InstitutionView } from '$lib/components/phase1-types.js';
  import { accountKind, money } from '$lib/format.js';

  type AccountDraft = {
    institutionId: string | null;
    displayName: string;
    kind: AccountView['kind'];
    nativeCurrency: string;
    accountRefMasked: string | null;
    creditLimit: string | null;
  };

  let accounts: AccountView[] = [];
  let institutions: InstitutionView[] = [];
  let editingAccount: AccountView | null = null;
  let loading = true;
  let pageError = '';
  let message = '';
  let institutionName = '';
  let savingInstitution = false;
  let editingInstitutionId = '';
  let editingInstitutionName = '';
  let baseCurrency = 'CAD';
  let selectedBaseCurrency = 'CAD';
  let switchingBase = false;
  let basePollTimer: ReturnType<typeof setTimeout> | undefined;

  $: assets = accounts.filter((account) => account.kind !== 'credit_card');
  $: cards = accounts.filter((account) => account.kind === 'credit_card');
  $: supportedCurrencies = Array.from(new Set(['CAD', 'USD', 'TZS', ...accounts.map((account) => account.nativeCurrency)])).sort();

  async function load() {
    loading = true;
    pageError = '';
    try {
      const [accountResult, institutionResult, settings] = await Promise.all([
        readJson<AccountsResponse>('/api/accounts'),
        readOptionalJson<InstitutionsResponse>('/api/institutions').catch(() => null),
        readOptionalJson<SettingsResponse>('/api/settings').catch(() => null)
      ]);
      accounts = accountResult.accounts;
      institutions = institutionResult?.institutions ?? [];
      baseCurrency = settings?.baseCurrency ?? accountResult.accounts[0]?.baseCurrency ?? 'CAD';
      selectedBaseCurrency = baseCurrency;
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'Accounts are temporarily unavailable.';
    } finally {
      loading = false;
    }
  }

  async function saveAccount(draft: AccountDraft) {
    const url = editingAccount ? `/api/accounts/${editingAccount.id}` : '/api/accounts';
    await sendJson(url, editingAccount ? 'PATCH' : 'POST', draft);
    message = editingAccount ? `${draft.displayName} was updated.` : `${draft.displayName} was added.`;
    editingAccount = null;
    await load();
  }

  async function addInstitution() {
    if (!institutionName.trim() || savingInstitution) return;
    savingInstitution = true;
    pageError = '';
    try {
      await sendJson('/api/institutions', 'POST', { name: institutionName.trim() });
      message = `${institutionName.trim()} was added.`;
      institutionName = '';
      await load();
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The institution could not be added.';
    } finally {
      savingInstitution = false;
    }
  }

  async function updateInstitution(id: string) {
    if (!editingInstitutionName.trim()) return;
    try {
      await sendJson(`/api/institutions/${id}`, 'PATCH', { name: editingInstitutionName.trim() });
      message = 'Institution updated.';
      editingInstitutionId = '';
      await load();
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The institution could not be updated.';
    }
  }

  async function changeBaseCurrency() {
    if (selectedBaseCurrency === baseCurrency || switchingBase) return;
    switchingBase = true;
    pageError = '';
    try {
      const accepted = await sendJson<{ jobId: string; kind: 'base_currency_rebuild'; status: 'queued' }>(
        '/api/settings/base-currency',
        'POST',
        { baseCurrency: selectedBaseCurrency }
      );
      message = `Valuation rebuild queued (${accepted.jobId.slice(0, 8)}…). Ledger will keep showing ${baseCurrency} until it completes.`;
      await pollBaseCurrency(accepted.jobId);
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The base-currency rebuild could not be queued.';
      selectedBaseCurrency = baseCurrency;
      switchingBase = false;
    }
  }

  async function pollBaseCurrency(jobId: string, attempt = 0): Promise<void> {
    if (attempt > 600) {
      pageError = 'The valuation rebuild is still running. Refresh this page to check its result.';
      selectedBaseCurrency = baseCurrency;
      switchingBase = false;
      return;
    }
    try {
      const job = await readJson<JobResponse>(`/api/jobs/${jobId}`, 'The valuation rebuild status could not be checked.');
      if (job.status === 'done') {
        if (job.kind !== 'base_currency_rebuild' || !job.result?.settingsUpdated) {
          throw new Error('The valuation rebuild finished without activating the new currency.');
        }
        await load();
        message = `${job.result.targetBaseCurrency} is now the active base currency. Every consolidated value was rebuilt atomically.`;
        switchingBase = false;
        return;
      }
      if (job.status === 'failed' || job.status === 'needs_ai') {
        pageError = job.error ?? 'The valuation rebuild failed. The previous base currency remains active.';
        selectedBaseCurrency = baseCurrency;
        switchingBase = false;
        return;
      }
      basePollTimer = setTimeout(() => void pollBaseCurrency(jobId, attempt + 1), 1500);
    } catch (error) {
      pageError = error instanceof Error ? error.message : 'The valuation rebuild status could not be checked.';
      selectedBaseCurrency = baseCurrency;
      switchingBase = false;
    }
  }

  onMount(load);
  onDestroy(() => {
    if (basePollTimer) clearTimeout(basePollTimer);
  });
</script>

<svelte:head>
  <title>Accounts · Ledger</title>
  <meta name="description" content="Manage asset accounts, credit cards, institutions, limits, and valuation currency." />
</svelte:head>

<div class="page">
  <header class="page-header">
    <div class="page-header-copy">
      <p class="eyebrow">Balance sheet</p>
      <h1>Assets and credit, separated.</h1>
      <p class="lede">Keep account identity and native currency explicit, add card limits, and choose the currency used for consolidated views.</p>
    </div>
  </header>

  {#if pageError}
    <div class="status-banner" role="alert"><strong>Accounts need attention.</strong><span>{pageError}</span><button class="button-secondary" type="button" on:click={load}>Try again</button></div>
  {:else if message}
    <div class="status-banner success" role="status"><strong>Saved.</strong><span>{message}</span><button class="text-button" type="button" on:click={() => (message = '')}>Dismiss</button></div>
  {/if}

  <section class="account-section" aria-labelledby="assets-title">
    <div class="section-title"><div><p class="eyebrow">Assets</p><h2 id="assets-title">Cash accounts</h2></div><span>{assets.length}</span></div>
    {#if loading}
      <div class="account-grid"><div class="skeleton-block"></div><div class="skeleton-block"></div></div>
    {:else if assets.length === 0}
      <div class="panel empty-state"><strong>No asset accounts</strong><p>Add chequing, savings, or wallet accounts below.</p></div>
    {:else}
      <div class="account-grid">
        {#each assets as account}
          <article class="account-card">
            <div class="account-top"><span>{account.institutionName ?? accountKind(account.kind)}</span><button class="text-button" type="button" on:click={() => (editingAccount = account)}>Edit</button></div>
            <h3>{account.displayName}</h3>
            <strong class="balance">{money(account.currentBalance, account.nativeCurrency)}</strong>
            {#if account.currentBalanceBase != null && account.baseCurrency && account.baseCurrency !== account.nativeCurrency}
              <small>{money(account.currentBalanceBase, account.baseCurrency)} consolidated</small>
            {/if}
            <p>{account.accountRefMasked ?? 'No account reference'} · {account.balanceBasis === 'balance' ? 'Verified balance' : 'Net activity'}</p>
          </article>
        {/each}
      </div>
    {/if}
  </section>

  <section class="account-section" aria-labelledby="cards-title">
    <div class="section-title"><div><p class="eyebrow">Liabilities</p><h2 id="cards-title">Credit cards</h2></div><span>{cards.length}</span></div>
    {#if loading}
      <div class="account-grid"><div class="skeleton-block"></div></div>
    {:else if cards.length === 0}
      <div class="panel empty-state"><strong>No credit cards</strong><p>Add a card below, then set its optional native-currency limit.</p></div>
    {:else}
      <div class="account-grid">
        {#each cards as account}
          <article class="account-card credit-card">
            <div class="account-top"><span>{account.institutionName ?? 'Credit card'}</span><button class="text-button" type="button" on:click={() => (editingAccount = account)}>Edit</button></div>
            <h3>{account.displayName}</h3>
            <strong class="balance">{money(account.currentBalance, account.nativeCurrency)}</strong>
            <small>Current card balance</small>
            <UtilizationMeter label={`${account.displayName} utilization`} value={account.utilizationPercent} used={account.usedCredit} limit={account.creditLimit} available={account.availableCredit} currency={account.nativeCurrency} />
          </article>
        {/each}
      </div>
    {/if}
  </section>

  <section class="management-grid">
    <article class="panel" aria-labelledby="account-form-title">
      <div class="panel-heading"><div><h2 id="account-form-title">{editingAccount ? `Edit ${editingAccount.displayName}` : 'Add an account'}</h2><p>Financial records are never removed by account editing.</p></div></div>
      <AccountForm account={editingAccount} {institutions} onSubmit={saveAccount} onCancel={() => (editingAccount = null)} />
    </article>

    <div class="side-stack">
      <article class="panel" aria-labelledby="currency-title">
        <div class="panel-heading"><div><h2 id="currency-title">Base currency</h2><p>Current consolidated valuation: {baseCurrency}</p></div></div>
        <form class="inline-form" on:submit|preventDefault={changeBaseCurrency}>
          <label class="field"><span>Display currency</span><select bind:value={selectedBaseCurrency}>{#each supportedCurrencies as currency}<option value={currency}>{currency}</option>{/each}</select></label>
          <button class="button" type="submit" disabled={selectedBaseCurrency === baseCurrency || switchingBase}>{switchingBase ? 'Queuing…' : 'Rebuild values'}</button>
        </form>
        <p class="fine-print">The switch becomes visible only after every historical rate is available and the rebuild succeeds.</p>
      </article>

      <article class="panel" aria-labelledby="institutions-title">
        <div class="panel-heading"><div><h2 id="institutions-title">Institutions</h2><p>Reusable names for account issuers and banks.</p></div></div>
        <form class="inline-form" on:submit|preventDefault={addInstitution}>
          <label class="field"><span>Institution name</span><input bind:value={institutionName} maxlength="120" placeholder="Bank or issuer" /></label>
          <button class="button" type="submit" disabled={!institutionName.trim() || savingInstitution}>Add</button>
        </form>
        {#if institutions.length}
          <ul class="institution-list">
            {#each institutions as institution}
              <li>
                {#if editingInstitutionId === institution.id}
                  <input bind:value={editingInstitutionName} aria-label={`New name for ${institution.name}`} />
                  <button class="text-button" type="button" on:click={() => updateInstitution(institution.id)}>Save</button>
                  <button class="text-button" type="button" on:click={() => (editingInstitutionId = '')}>Cancel</button>
                {:else}
                  <span>{institution.name}</span>
                  <button class="text-button" type="button" on:click={() => { editingInstitutionId = institution.id; editingInstitutionName = institution.name; }}>Rename</button>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </article>
    </div>
  </section>
</div>

<style>
  .account-section { display: grid; gap: 0.8rem; }
  .section-title { display: flex; align-items: end; justify-content: space-between; gap: 1rem; }
  .section-title h2,
  .section-title p { margin: 0; }
  .section-title h2 { margin-top: 0.18rem; font-size: 1.45rem; letter-spacing: -0.04em; }
  .section-title > span { display: grid; width: 32px; height: 32px; place-items: center; color: var(--forest); border-radius: 50%; background: var(--mint); font-size: 0.7rem; font-weight: 850; }
  .account-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.75rem; }
  .account-card { display: grid; min-height: 210px; padding: 1rem; align-content: space-between; gap: 0.45rem; border: 1px solid var(--line); border-radius: 17px; background: var(--paper); box-shadow: var(--shadow); }
  .account-card.credit-card { min-height: 255px; }
  .account-top { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  .account-top > span,
  .account-card small,
  .account-card p { color: var(--muted); font-size: 0.64rem; }
  .account-card h3 { margin: 0.6rem 0 0; font-size: 1rem; letter-spacing: -0.025em; }
  .account-card .balance { color: var(--forest); font-size: 1.65rem; letter-spacing: -0.05em; font-variant-numeric: tabular-nums; }
  .account-card p { margin: 0.4rem 0 0; line-height: 1.45; }
  .management-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr); gap: 1rem; align-items: start; }
  .side-stack { display: grid; gap: 1rem; }
  .inline-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.55rem; align-items: end; }
  .fine-print { margin: 0.7rem 0 0; color: var(--muted); font-size: 0.64rem; line-height: 1.5; }
  .institution-list { padding: 0; margin: 1rem 0 0; list-style: none; }
  .institution-list li { display: flex; min-height: 42px; align-items: center; gap: 0.4rem; border-top: 1px solid #e8e9e3; font-size: 0.72rem; }
  .institution-list li > span { flex: 1; }
  .institution-list input { flex: 1; min-width: 0; min-height: 34px; padding: 0 0.5rem; border: 1px solid var(--line); border-radius: 7px; }
  @media (max-width: 960px) {
    .account-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .management-grid { grid-template-columns: 1fr; }
  }
  @media (max-width: 600px) {
    .account-grid { grid-template-columns: 1fr; }
    .inline-form { grid-template-columns: 1fr; }
  }
</style>
