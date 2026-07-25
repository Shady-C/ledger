<script lang="ts">
  import { page } from '$app/stores';
  import BrandMark from '$lib/components/BrandMark.svelte';
  import MarketScopeSelector from '$lib/components/MarketScopeSelector.svelte';
  import SetupPrompt from '$lib/components/SetupPrompt.svelte';
  import { marketState, withMarket } from '$lib/market-scope.js';
  import '../app.css';

  const desktopNavigation = [
    { href: '/', label: 'Dashboard', shortLabel: 'Home', icon: '⌂' },
    { href: '/transactions', label: 'Transactions', shortLabel: 'Activity', icon: '↕' },
    { href: '/accounts', label: 'Accounts', shortLabel: 'Accounts', icon: '▣' },
    { href: '/categories', label: 'Categories', shortLabel: 'Categories', icon: '◫' },
    { href: '/insights', label: 'Insights', shortLabel: 'Insights', icon: '◉' },
    { href: '/imports', label: 'Imports', shortLabel: 'Imports', icon: '↑' },
    { href: '/more', label: 'More', shortLabel: 'More', icon: '•••' }
  ] as const;

  const mobileNavigation = [
    { href: '/', label: 'Home', icon: '⌂' },
    { href: '/transactions', label: 'Activity', icon: '↕' },
    { href: '/insights', label: 'Insights', icon: '◉' },
    { href: '/more', label: 'More', icon: '•••' }
  ] as const;

  function isCurrent(href: string) {
    return href === '/' ? $page.url.pathname === '/' : $page.url.pathname.startsWith(href);
  }

  function isMobileCurrent(href: string) {
    if (href === '/more') {
      return ['/more', '/accounts', '/categories', '/imports', '/settings'].some((path) =>
        $page.url.pathname.startsWith(path)
      );
    }
    return isCurrent(href);
  }

  function isDesktopCurrent(href: string) {
    return href === '/more' && $page.url.pathname.startsWith('/settings') ? true : isCurrent(href);
  }

  $: showsMarketScope = $page.url.pathname === '/'
    || ['/transactions', '/accounts', '/insights', '/imports'].some((path) => $page.url.pathname.startsWith(path));

  function navigationHref(href: string) {
    return ['/', '/transactions', '/accounts', '/insights', '/imports'].includes(href) && $marketState.ready
      ? withMarket(href, $marketState.market)
      : href;
  }
</script>

<a class="skip-link" href="#main-content">Skip to content</a>

<header class="app-header">
  <div class="header-inner">
    <a class="brand" href="/" aria-label="Ledger dashboard">
      <BrandMark />
      <span>Ledger</span>
    </a>

    <nav class="desktop-nav" aria-label="Primary navigation">
      {#each desktopNavigation as item}
        <a class:active={isDesktopCurrent(item.href)} href={navigationHref(item.href)} aria-current={isDesktopCurrent(item.href) ? 'page' : undefined}>
          {item.label}
        </a>
      {/each}
    </nav>

    <div class="privacy"><span aria-hidden="true"></span> Self-hosted &amp; private</div>
  </div>
</header>

{#if showsMarketScope}
  <MarketScopeSelector />
  <SetupPrompt />
{/if}

<main id="main-content" class="app-main">
  <slot />
</main>

<footer class="app-footer">
  <span>Ledger</span>
  <p>Deterministic by design. Financial arithmetic stays in the code path.</p>
</footer>

<nav class="mobile-nav" aria-label="Mobile navigation">
  {#each mobileNavigation as item}
    <a class:active={isMobileCurrent(item.href)} href={navigationHref(item.href)} aria-current={isMobileCurrent(item.href) ? 'page' : undefined}>
      <span aria-hidden="true">{item.icon}</span>
      {item.label}
    </a>
  {/each}
</nav>

<style>
  .skip-link {
    position: fixed;
    z-index: 100;
    top: 0.5rem;
    left: 0.5rem;
    padding: 0.65rem 0.85rem;
    color: white;
    border-radius: 8px;
    background: var(--forest);
    transform: translateY(-150%);
  }

  .skip-link:focus { transform: translateY(0); }

  .app-header {
    position: sticky;
    z-index: 20;
    top: 0;
    border-bottom: 1px solid rgb(205 211 204 / 75%);
    background: rgb(244 242 236 / 90%);
    backdrop-filter: blur(16px);
  }

  .header-inner {
    display: grid;
    grid-template-columns: auto 1fr auto;
    width: min(var(--page-width), calc(100% - 2rem));
    min-height: 68px;
    margin: 0 auto;
    align-items: center;
    gap: 2rem;
  }

  .brand {
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    color: var(--forest);
    font-size: 1rem;
    font-weight: 850;
    letter-spacing: -0.04em;
    text-decoration: none;
  }

  .desktop-nav {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.2rem;
  }

  .desktop-nav a {
    padding: 0.52rem 0.72rem;
    color: var(--muted);
    border-radius: 9px;
    font-size: 0.72rem;
    font-weight: 750;
    text-decoration: none;
  }

  .desktop-nav a:hover,
  .desktop-nav a.active {
    color: var(--forest);
    background: rgb(167 215 200 / 42%);
  }

  .privacy {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    color: var(--muted);
    font-size: 0.66rem;
    font-weight: 700;
    white-space: nowrap;
  }

  .privacy span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #4eae86;
    box-shadow: 0 0 0 4px rgb(78 174 134 / 12%);
  }

  .app-main {
    width: min(var(--page-width), calc(100% - 2rem));
    min-height: calc(100vh - 170px);
    margin: 0 auto;
  }

  .app-footer {
    display: flex;
    width: min(var(--page-width), calc(100% - 2rem));
    margin: 3rem auto 0;
    padding: 1.5rem 0 2.5rem;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    color: var(--muted);
    border-top: 1px solid #d8d9d2;
    font-size: 0.68rem;
  }

  .app-footer span { color: var(--forest); font-weight: 850; }
  .app-footer p { margin: 0; text-align: right; }
  .mobile-nav { display: none; }

  @media (max-width: 840px) {
    .header-inner { grid-template-columns: auto 1fr; }
    .desktop-nav { display: none; }
    .privacy { justify-self: end; }
    .app-footer { display: none; }

    .mobile-nav {
      position: fixed;
      z-index: 30;
      right: 0.6rem;
      bottom: max(0.6rem, env(safe-area-inset-bottom));
      left: 0.6rem;
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      overflow: hidden;
      padding: 0.3rem;
      border: 1px solid rgb(255 255 255 / 12%);
      border-radius: 17px;
      background: rgb(16 43 42 / 96%);
      box-shadow: 0 18px 48px rgb(13 39 37 / 30%);
      backdrop-filter: blur(14px);
    }

    .mobile-nav a {
      display: grid;
      min-width: 0;
      min-height: 48px;
      padding: 0.28rem 0.1rem;
      place-content: center;
      justify-items: center;
      gap: 0.1rem;
      color: #bcd0ca;
      border-radius: 11px;
      font-size: 0.57rem;
      font-weight: 750;
      text-decoration: none;
    }

    .mobile-nav a span { font-size: 1rem; line-height: 1; }
    .mobile-nav a.active { color: var(--forest); background: var(--mint); }
  }

  @media (max-width: 520px) {
    .header-inner,
    .app-main,
    .app-footer { width: min(100% - 1.2rem, var(--page-width)); }
    .privacy { font-size: 0; }
    .privacy::after { content: 'Private'; font-size: 0.64rem; }
    .app-footer { align-items: flex-start; }
  }
</style>
