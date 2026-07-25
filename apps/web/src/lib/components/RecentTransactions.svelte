<script lang="ts">
  import { money, shortDate } from '$lib/format.js';
  import type { TransactionView } from './phase1-types.js';

  export let transactions: TransactionView[] = [];
  export let loading = false;
  export let viewAllHref = '/transactions';
</script>

<section class="panel recent" aria-labelledby="recent-transactions-title">
  <div class="panel-heading">
    <div>
      <h2 id="recent-transactions-title">Recent transactions</h2>
      <p>The latest activity across every account.</p>
    </div>
    <a class="text-button" href={viewAllHref}>View all <span aria-hidden="true">→</span></a>
  </div>

  {#if loading}
    <div class="loading" aria-label="Loading recent transactions" aria-busy="true">
      {#each Array(5) as _}<span></span>{/each}
    </div>
  {:else if transactions.length === 0}
    <div class="empty-state">
      <strong>No activity yet</strong>
      <p>Imported transactions will appear here.</p>
    </div>
  {:else}
    <ol>
      {#each transactions.slice(0, 6) as transaction}
        <li>
          <span class="date">{shortDate(transaction.postedDate ?? transaction.bookedDate)}</span>
          <span class="description">
            <strong>{transaction.merchantName ?? transaction.description}</strong>
            <small>{transaction.accountName} · {transaction.categoryName ?? 'Uncategorized'}</small>
          </span>
          <strong class:credit={Number(transaction.amountNative) < 0} class="amount">
            {money(transaction.amountNative, transaction.currencyNative)}
          </strong>
        </li>
      {/each}
    </ol>
  {/if}
</section>

<style>
  .recent { min-height: 100%; }
  ol { padding: 0; margin: 0; list-style: none; }
  li {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr) auto;
    gap: 0.75rem;
    padding: 0.76rem 0;
    align-items: center;
    border-top: 1px solid #e8e9e3;
  }
  .date { color: var(--muted); font-size: 0.68rem; white-space: nowrap; }
  .description { display: grid; min-width: 0; gap: 0.15rem; }
  .description strong { overflow: hidden; font-size: 0.75rem; text-overflow: ellipsis; white-space: nowrap; }
  .description small { overflow: hidden; color: var(--muted); font-size: 0.63rem; text-overflow: ellipsis; white-space: nowrap; }
  .amount { font-size: 0.74rem; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .amount.credit { color: var(--success); }
  .loading { display: grid; gap: 0.55rem; }
  .loading span { display: block; height: 48px; border-radius: 9px; background: #efefe9; animation: pulse 1s ease-in-out infinite alternate; }
  @keyframes pulse { to { opacity: 0.5; } }
  @media (max-width: 520px) {
    li { grid-template-columns: minmax(0, 1fr) auto; }
    .date { grid-column: 1 / -1; }
  }
</style>
