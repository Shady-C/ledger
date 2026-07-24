<script lang="ts">
  import { accountKind, money } from '$lib/format.js';
  import type { AccountView } from './phase1-types.js';
  import UtilizationMeter from './UtilizationMeter.svelte';

  export let accounts: AccountView[] = [];
  export let loading = false;
  export let selected = '';
  export let onSelect: (id: string) => void = () => undefined;
</script>

<section class="accounts" aria-labelledby="accounts-heading">
  <div class="section-heading">
    <div>
      <p>Portfolio</p>
      <h2 id="accounts-heading">Your accounts</h2>
    </div>
    <span>{accounts.length} {accounts.length === 1 ? 'account' : 'accounts'}</span>
  </div>

  {#if loading}
    <div class="cards" aria-label="Loading accounts" aria-busy="true">
      <div class="skeleton"></div>
      <div class="skeleton"></div>
    </div>
  {:else if accounts.length === 0}
    <div class="empty">
      <div class="empty-mark" aria-hidden="true">+</div>
      <div>
        <strong>No accounts yet</strong>
        <p>Seed an account, then import its first statement to begin your ledger.</p>
      </div>
    </div>
  {:else}
    <div class="cards">
      <button class:active={selected === ''} type="button" on:click={() => onSelect('')}>
        <span class="eyebrow">All accounts</span>
        <strong>{accounts.length}</strong>
        <span class="meta">Consolidated view</span>
      </button>
      {#each accounts as account}
        <button class:active={selected === account.id} type="button" on:click={() => onSelect(account.id)}>
          <span class="eyebrow">{account.institutionName ?? accountKind(account.kind)}</span>
          <strong>{money(account.currentBalance, account.nativeCurrency)}</strong>
          <span class="meta">
            {account.displayName}{account.accountRefMasked ? ` · ${account.accountRefMasked}` : ''}
            · {account.balanceBasis === 'net_activity' ? 'Net activity' : 'Current balance'}
          </span>
          {#if account.kind === 'credit_card'}
            <UtilizationMeter
              compact
              label={`${account.displayName} utilization`}
              value={account.utilizationPercent}
              used={account.usedCredit}
              limit={account.creditLimit}
              available={account.availableCredit}
              currency={account.nativeCurrency}
            />
          {/if}
        </button>
      {/each}
    </div>
  {/if}
</section>

<style>
  .accounts {
    min-width: 0;
  }

  .section-heading {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .section-heading p,
  .section-heading h2 {
    margin: 0;
  }

  .section-heading p {
    margin-bottom: 0.25rem;
    color: var(--coral);
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.11em;
    text-transform: uppercase;
  }

  .section-heading h2 {
    font-size: clamp(1.25rem, 2vw, 1.55rem);
    letter-spacing: -0.035em;
  }

  .section-heading > span {
    color: var(--muted);
    font-size: 0.78rem;
    font-weight: 700;
  }

  .cards {
    display: grid;
    grid-auto-columns: minmax(220px, 1fr);
    grid-auto-flow: column;
    gap: 0.8rem;
    overflow-x: auto;
    padding: 0.15rem 0 0.6rem;
    scrollbar-width: thin;
  }

  button,
  .skeleton {
    min-height: 124px;
    border: 1px solid var(--line);
    border-radius: 17px;
  }

  button {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: space-between;
    min-width: 220px;
    gap: 0.7rem;
    padding: 1rem;
    color: var(--ink);
    text-align: left;
    background: rgb(252 251 247 / 82%);
    transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
  }

  button:hover {
    transform: translateY(-2px);
    border-color: #aebbb6;
  }

  button.active {
    color: white;
    border-color: var(--forest);
    background: var(--forest);
    box-shadow: var(--shadow);
  }

  .eyebrow,
  .meta {
    color: var(--muted);
    font-size: 0.72rem;
    font-weight: 700;
  }

  button.active .eyebrow,
  button.active .meta {
    color: #bcd0ca;
  }

  strong {
    font-size: 1.28rem;
    letter-spacing: -0.04em;
  }

  button :global(.utilization) { width: 100%; }

  .skeleton {
    min-width: 220px;
    background: linear-gradient(100deg, #e8e7e1 25%, #f7f6f1 45%, #e8e7e1 65%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
  }

  .empty {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 1.2rem;
    border: 1px dashed #b8c1bc;
    border-radius: 17px;
    background: rgb(252 251 247 / 62%);
  }

  .empty-mark {
    display: grid;
    flex: 0 0 auto;
    width: 42px;
    height: 42px;
    place-items: center;
    color: var(--forest);
    border-radius: 50%;
    background: var(--mint);
    font-size: 1.5rem;
  }

  .empty p {
    margin: 0.25rem 0 0;
    color: var(--muted);
    font-size: 0.84rem;
  }

  @keyframes shimmer {
    to { background-position-x: -200%; }
  }
</style>
