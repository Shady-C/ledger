<script lang="ts">
  import type {
    AccountSummary,
    CategorySummary,
    TransactionPage,
    TransactionSort
  } from '@ledger/shared-types';
  import { money, shortDate } from '$lib/format.js';

  export let data: TransactionPage = { items: [], page: 1, pageSize: 25, total: 0, totalPages: 0 };
  export let accounts: AccountSummary[] = [];
  export let categories: CategorySummary[] = [];
  export let loading = false;
  export let search = '';
  export let accountId = '';
  export let categoryId = '';
  export let direction = '';
  export let sort: TransactionSort = 'booked_date_desc';
  export let onFilter: (filters: {
    search: string;
    accountId: string;
    categoryId: string;
    direction: string;
    sort: TransactionSort;
  }) => void = () => undefined;
  export let onPage: (page: number) => void = () => undefined;
  export let onPageSize: (pageSize: number) => void = () => undefined;

  function submit() {
    onFilter({ search, accountId, categoryId, direction, sort });
  }
</script>

<section class="transactions" aria-labelledby="transactions-title">
  <div class="heading">
    <div>
      <p>Canonical ledger</p>
      <h2 id="transactions-title">Transactions</h2>
    </div>
    <span>{data.total.toLocaleString()} records</span>
  </div>

  <form class="filters" on:submit|preventDefault={submit}>
    <label class="search">
      <span class="sr-only">Search transactions</span>
      <span aria-hidden="true">⌕</span>
      <input bind:value={search} type="search" placeholder="Search descriptions or merchants" maxlength="120" />
    </label>
    <label>
      <span class="sr-only">Filter by account</span>
      <select bind:value={accountId} on:change={submit}>
        <option value="">All accounts</option>
        {#each accounts as account}
          <option value={account.id}>{account.displayName}</option>
        {/each}
      </select>
    </label>
    <label>
      <span class="sr-only">Filter by direction</span>
      <select bind:value={direction} on:change={submit}>
        <option value="">All activity</option>
        <option value="debit">Charges</option>
        <option value="credit">Credits</option>
        <option value="payment">Payments</option>
        <option value="fee">Fees</option>
        <option value="refund">Refunds</option>
        <option value="interest">Interest</option>
      </select>
    </label>
    <label>
      <span class="sr-only">Filter by category</span>
      <select bind:value={categoryId} on:change={submit}>
        <option value="">All categories</option>
        {#each categories as category}
          <option value={category.id}>{category.name}</option>
        {/each}
      </select>
    </label>
    <label>
      <span class="sr-only">Sort transactions</span>
      <select bind:value={sort} on:change={submit}>
        <option value="booked_date_desc">Newest first</option>
        <option value="booked_date_asc">Oldest first</option>
        <option value="amount_desc">Largest amount</option>
        <option value="amount_asc">Smallest amount</option>
      </select>
    </label>
    <button type="submit">Search</button>
  </form>

  <div class="table-wrap" class:loading aria-busy={loading}>
    <table>
      <thead>
        <tr>
          <th scope="col">Processed date</th>
          <th scope="col">Description</th>
          <th scope="col">Category</th>
          <th scope="col" class="number">Amount</th>
          <th scope="col" class="number">End-of-day position</th>
        </tr>
      </thead>
      <tbody>
        {#if loading}
          {#each Array(5) as _}
            <tr class="placeholder">
              <td><i></i></td><td><i></i></td><td><i></i></td><td><i></i></td><td><i></i></td>
            </tr>
          {/each}
        {:else if data.items.length === 0}
          <tr>
            <td colspan="5">
              <div class="empty">
                <strong>{search || accountId || categoryId || direction ? 'No matching transactions' : 'Your ledger is empty'}</strong>
                <span>{search || accountId || categoryId || direction ? 'Try clearing one of the filters.' : 'Imported transactions will appear here.'}</span>
              </div>
            </td>
          </tr>
        {:else}
          {#each data.items as transaction}
            <tr>
              <td class="date">
                <span>{shortDate(transaction.postedDate ?? transaction.bookedDate)}</span>
                {#if transaction.postedDate && transaction.postedDate !== transaction.bookedDate}
                  <small>Booked {shortDate(transaction.bookedDate)}</small>
                {/if}
              </td>
              <td>
                <div class="description">
                  <strong>{transaction.merchantName ?? transaction.description}</strong>
                  <span>{transaction.accountName}{transaction.merchantName ? ` · ${transaction.description}` : ''}</span>
                </div>
              </td>
              <td><span class="category">{transaction.categoryName ?? 'Uncategorized'}</span></td>
              <td class:credit={Number(transaction.amountNative) < 0} class="number amount">
                {money(transaction.amountNative, transaction.currencyNative)}
              </td>
              <td class="number balance">{money(transaction.runningBalance, transaction.currencyBase)}</td>
            </tr>
          {/each}
        {/if}
      </tbody>
    </table>
  </div>

  {#if data.total > 0}
    <nav class="pagination" aria-label="Transaction pages">
      <button type="button" disabled={data.page <= 1 || loading} on:click={() => onPage(data.page - 1)}>Previous</button>
      <label>
        <span>Page</span>
        <select
          aria-label="Go to transaction page"
          value={data.page}
          disabled={loading}
          on:change={(event) => onPage(Number(event.currentTarget.value))}
        >
          {#each Array(data.totalPages) as _, index}
            <option value={index + 1}>{index + 1}</option>
          {/each}
        </select>
        <span>of {data.totalPages}</span>
      </label>
      <label>
        <span>Rows</span>
        <select
          aria-label="Transactions per page"
          value={data.pageSize}
          disabled={loading}
          on:change={(event) => onPageSize(Number(event.currentTarget.value))}
        >
          {#each [10, 25, 50, 100] as size}
            <option value={size}>{size}</option>
          {/each}
        </select>
      </label>
      <button type="button" disabled={data.page >= data.totalPages || loading} on:click={() => onPage(data.page + 1)}>Next</button>
    </nav>
  {/if}
</section>

<style>
  .transactions {
    min-width: 0;
    padding: clamp(1rem, 2.5vw, 1.6rem);
    border: 1px solid var(--line);
    border-radius: 22px;
    background: var(--paper);
    box-shadow: var(--shadow);
  }

  .heading {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .heading p,
  .heading h2 { margin: 0; }
  .heading p {
    margin-bottom: 0.25rem;
    color: var(--coral);
    font-size: 0.7rem;
    font-weight: 800;
    letter-spacing: 0.11em;
    text-transform: uppercase;
  }

  .heading h2 { font-size: 1.45rem; letter-spacing: -0.04em; }
  .heading > span { color: var(--muted); font-size: 0.75rem; font-weight: 700; }

  .filters {
    display: grid;
    grid-template-columns: minmax(210px, 1.6fr) repeat(4, minmax(118px, 0.7fr)) auto;
    gap: 0.55rem;
    margin-bottom: 1rem;
  }

  .filters label { min-width: 0; }
  .filters input,
  .filters select,
  .filters button {
    width: 100%;
    min-height: 40px;
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: 9px;
    background: #f8f7f2;
    font-size: 0.74rem;
  }

  .filters select { padding: 0 0.65rem; }
  .filters button {
    width: auto;
    padding: 0 1rem;
    color: white;
    border-color: var(--forest);
    background: var(--forest);
    font-weight: 800;
  }

  .search { position: relative; }
  .search > span:not(.sr-only) {
    position: absolute;
    top: 50%;
    left: 0.8rem;
    color: var(--muted);
    transform: translateY(-50%);
  }
  .search input { padding: 0 0.75rem 0 2.2rem; }

  .table-wrap {
    overflow-x: auto;
    border: 1px solid #e8e8e1;
    border-radius: 13px;
  }

  table {
    width: 100%;
    min-width: 780px;
    border-collapse: collapse;
  }

  th,
  td {
    padding: 0.78rem 0.85rem;
    border-bottom: 1px solid #e9e9e3;
    text-align: left;
  }

  th {
    color: var(--muted);
    background: #f6f5ef;
    font-size: 0.66rem;
    font-weight: 800;
    letter-spacing: 0.07em;
    text-transform: uppercase;
  }

  tbody tr:last-child td { border-bottom: 0; }
  tbody tr:not(.placeholder):hover { background: #faf9f5; }
  td { font-size: 0.75rem; }
  .number { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .date { color: var(--muted); white-space: nowrap; }
  .date small { display: block; margin-top: 0.12rem; font-size: 0.62rem; }
  .description { display: grid; gap: 0.17rem; min-width: 220px; }
  .description strong { font-size: 0.77rem; }
  .description span { max-width: 42ch; overflow: hidden; color: var(--muted); font-size: 0.65rem; text-overflow: ellipsis; white-space: nowrap; }
  .category { display: inline-block; padding: 0.25rem 0.5rem; color: #41504d; border-radius: 999px; background: #edf0eb; font-size: 0.66rem; font-weight: 700; }
  .amount { color: var(--ink); font-weight: 800; }
  .amount.credit { color: #237a64; }
  .balance { color: var(--muted); }

  .empty {
    display: grid;
    min-height: 180px;
    place-content: center;
    justify-items: center;
    color: var(--muted);
  }
  .empty strong { margin-bottom: 0.3rem; color: var(--ink); }

  .placeholder i {
    display: block;
    width: 80%;
    height: 12px;
    border-radius: 5px;
    background: #ecece6;
    animation: pulse 1s ease-in-out infinite alternate;
  }

  .pagination {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 0.8rem;
    margin-top: 1rem;
    color: var(--muted);
    font-size: 0.72rem;
  }

  .pagination label {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
  }

  .pagination button,
  .pagination select {
    padding: 0.45rem 0.7rem;
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: 8px;
    background: white;
    font-size: 0.7rem;
    font-weight: 700;
  }
  .pagination select { padding-right: 1.7rem; }
  .pagination button:disabled,
  .pagination select:disabled { opacity: 0.45; }

  @keyframes pulse { to { opacity: 0.45; } }

  @media (max-width: 960px) {
    .filters { grid-template-columns: 1fr 1fr; }
    .search { grid-column: 1 / -1; }
    .filters button { width: 100%; }
  }

  @media (max-width: 560px) {
    .filters { grid-template-columns: 1fr; }
    .search { grid-column: 1; }
    .heading { align-items: start; }
    .transactions { border-radius: 17px; }
  }
</style>
