<script lang="ts">
  import { accountKind } from '$lib/format.js';
  import type { MarketCode } from '@ledger/shared-types';
  import type { AccountView, InstitutionView } from './phase1-types.js';

  type AccountDraft = {
    institutionId: string | null;
    displayName: string;
    kind: AccountView['kind'];
    nativeCurrency: string;
    marketCode: MarketCode;
    accountRefMasked: string | null;
    creditLimit: string | null;
  };

  export let account: AccountView | null = null;
  export let institutions: InstitutionView[] = [];
  export let defaultMarket: MarketCode | '' = '';
  export let onSubmit: (draft: AccountDraft) => Promise<void> = async () => undefined;
  export let onCancel: () => void = () => undefined;

  let displayName = '';
  let institutionId = '';
  let kind: AccountView['kind'] = 'chequing';
  let nativeCurrency = 'CAD';
  let marketCode: MarketCode | '' = '';
  let accountRefMasked = '';
  let creditLimit = '';
  let saving = false;
  let message = '';
  let initializedFor: string | null | undefined = undefined;
  let initializationKey = '';
  const maskedReferencePattern = '[^0-9]+[0-9]{2,6}';

  $: initializationKey = account?.id ?? `new-${defaultMarket}`;
  $: if (initializedFor !== initializationKey) {
    initializedFor = initializationKey;
    displayName = account?.displayName ?? '';
    institutionId = account?.institutionId ?? '';
    kind = account?.kind ?? 'chequing';
    marketCode = account ? (account.marketCode ?? '') : defaultMarket;
    nativeCurrency = account?.nativeCurrency ?? (marketCode === 'TZ' ? 'TZS' : 'CAD');
    accountRefMasked = account?.accountRefMasked ?? '';
    creditLimit = account?.creditLimit ?? '';
    message = '';
  }
  $: locked = Boolean(account && (account.hasActivity || account.lastStatementDate));

  async function submit() {
    message = '';
    if (!displayName.trim()) {
      message = 'Enter an account name.';
      return;
    }
    if (kind === 'credit_card' && creditLimit && Number(creditLimit) <= 0) {
      message = 'Credit limit must be greater than zero.';
      return;
    }
    if (!marketCode) {
      message = 'Choose the account market.';
      return;
    }
    saving = true;
    try {
      await onSubmit({
        institutionId: institutionId || null,
        displayName: displayName.trim(),
        kind,
        nativeCurrency: nativeCurrency.trim().toUpperCase(),
        marketCode,
        accountRefMasked: accountRefMasked.trim() || null,
        creditLimit: kind === 'credit_card' && creditLimit ? String(creditLimit) : null
      });
      if (!account) {
        displayName = '';
        accountRefMasked = '';
        creditLimit = '';
      }
    } catch (error) {
      message = error instanceof Error ? error.message : 'The account could not be saved.';
    } finally {
      saving = false;
    }
  }
</script>

<form class="form-grid" on:submit|preventDefault={submit}>
  <label class="field">
    <span>Account name</span>
    <input bind:value={displayName} required maxlength="120" placeholder="Everyday chequing" />
  </label>
  <label class="field">
    <span>Institution</span>
    <select bind:value={institutionId}>
      <option value="">No institution</option>
      {#each institutions as institution}
        <option value={institution.id}>{institution.name}</option>
      {/each}
    </select>
  </label>
  <label class="field">
    <span>Account type</span>
    <select bind:value={kind} disabled={locked}>
      {#each ['chequing', 'savings', 'wallet', 'credit_card'] as value}
        <option value={value}>{accountKind(value)}</option>
      {/each}
    </select>
    {#if locked}<small>Type is locked after the first imported record.</small>{/if}
  </label>
  <label class="field">
    <span>Market</span>
    <select bind:value={marketCode} required aria-label="Account market">
      <option value="" disabled>Choose a market</option>
      <option value="CA">Canada</option>
      <option value="TZ">Tanzania</option>
    </select>
    <small>Controls country scopes, not the account currency.</small>
  </label>
  <label class="field">
    <span>Native currency</span>
    <input bind:value={nativeCurrency} disabled={locked} required minlength="3" maxlength="3" autocapitalize="characters" />
    {#if locked}<small>Currency is locked after the first imported record.</small>{/if}
  </label>
  <label class="field">
    <span>Masked reference</span>
    <input bind:value={accountRefMasked} maxlength="64" pattern={maskedReferencePattern} placeholder="•••• 4812" />
    <small>Enter a masked label and only the final 2–6 digits; never enter a full account number.</small>
  </label>
  {#if kind === 'credit_card'}
    <label class="field">
      <span>Credit limit ({nativeCurrency || 'native currency'})</span>
      <input bind:value={creditLimit} type="text" inputmode="decimal" pattern="[0-9]+(?:\.[0-9]+)?" placeholder="Optional" />
      <small>Used for utilization only; it never changes net worth.</small>
    </label>
  {/if}
  <div class="form-actions">
    {#if message}<span class="form-message" role="alert">{message}</span>{/if}
    {#if account}<button class="button-secondary" type="button" disabled={saving} on:click={onCancel}>Cancel</button>{/if}
    <button class="button" type="submit" disabled={saving}>{saving ? 'Saving…' : account ? 'Save account' : 'Add account'}</button>
  </div>
</form>

<style>
  .form-message { margin-right: auto; color: var(--danger); font-size: 0.68rem; }
</style>
