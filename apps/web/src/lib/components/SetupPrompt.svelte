<script lang="ts">
  import { onMount } from 'svelte';
  import type { AccountsResponse } from '@ledger/shared-types';
  import { marketState } from '$lib/market-scope.js';

  let unassigned = 0;
  let checked = false;
  let profileMissing = false;
  $: profileMissing = Boolean($marketState.settings && !$marketState.settings.marketProfile);

  async function check() {
    try {
      const response = await fetch('/api/accounts', { cache: 'no-store', headers: { accept: 'application/json' } });
      if (response.ok) {
        const result = (await response.json()) as AccountsResponse;
        unassigned = result.accounts.filter((account) => account.marketCode == null).length;
      }
    } catch {
      unassigned = 0;
    } finally {
      checked = true;
    }
  }

  onMount(() => {
    void check();
    window.addEventListener('ledger:accounts-changed', check);
    return () => window.removeEventListener('ledger:accounts-changed', check);
  });
</script>

{#if checked && $marketState.ready && (profileMissing || unassigned > 0)}
  <aside class="setup-prompt" aria-label="Ledger setup reminder">
    <span aria-hidden="true">○</span>
    <p>
      <strong>Finish market setup.</strong>
      {#if profileMissing && unassigned > 0}
        Choose a default market and classify {unassigned} {unassigned === 1 ? 'account' : 'accounts'}.
      {:else if profileMissing}
        Choose a default market for new accounts and first visits.
      {:else}
        Classify {unassigned} existing {unassigned === 1 ? 'account' : 'accounts'} to include them in Canada or Tanzania views.
      {/if}
    </p>
    <a href="/settings">Open settings</a>
  </aside>
{/if}

<style>
  .setup-prompt { display: flex; width: min(var(--page-width), calc(100% - 2rem)); margin: 0.35rem auto 0; padding: 0.55rem 0.7rem; align-items: center; gap: 0.55rem; color: #285049; border: 1px solid #bad3cb; border-radius: 10px; background: #edf7f3; font-size: 0.64rem; }
  .setup-prompt > span { display: grid; flex: 0 0 auto; width: 22px; height: 22px; place-items: center; border-radius: 50%; background: #d7eee6; font-weight: 900; }
  p { flex: 1; margin: 0; line-height: 1.45; }
  a { color: var(--forest); font-weight: 850; white-space: nowrap; }
  @media (max-width: 600px) { .setup-prompt { width: min(100% - 1.2rem, var(--page-width)); align-items: flex-start; } }
</style>
