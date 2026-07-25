import { get, writable } from 'svelte/store';
import type { MarketCode, SettingsResponse } from '@ledger/shared-types';

export type MarketSelection = MarketCode | '';

type MarketState = {
  ready: boolean;
  market: MarketSelection;
  settings: SettingsResponse | null;
};

const STORAGE_KEY = 'ledger.market';
const initialState: MarketState = { ready: false, market: '', settings: null };

export const marketState = writable<MarketState>(initialState);

let initializing: Promise<MarketState> | null = null;

function marketFrom(value: string | null | undefined): MarketSelection | null {
  if (value === 'CA' || value === 'TZ') return value;
  if (value === '' || value === 'ALL') return '';
  return null;
}

export async function initializeMarketScope(url = new URL(window.location.href)): Promise<MarketState> {
  const explicit = url.searchParams.has('market')
    ? marketFrom(url.searchParams.get('market'))
    : null;

  if (get(marketState).ready) {
    if (explicit !== null && explicit !== get(marketState).market) {
      setMarketScope(explicit, false);
    }
    return get(marketState);
  }

  if (initializing) return initializing;
  initializing = (async () => {
    let settings: SettingsResponse | null = null;
    try {
      const response = await fetch('/api/settings', {
        cache: 'no-store',
        headers: { accept: 'application/json' }
      });
      if (response.ok) settings = (await response.json()) as SettingsResponse;
    } catch {
      // Scope selection remains usable if settings are temporarily unavailable.
    }

    let remembered: MarketSelection | null = null;
    try {
      remembered = marketFrom(window.localStorage.getItem(STORAGE_KEY));
    } catch {
      // Browser storage can be disabled; the URL/profile fallback still works.
    }
    const market = explicit ?? remembered ?? settings?.marketProfile ?? '';
    const state = { ready: true, market, settings } satisfies MarketState;
    marketState.set(state);
    return state;
  })().finally(() => {
    initializing = null;
  });
  return initializing;
}

export function setMarketScope(market: MarketSelection, announce = true) {
  const current = get(marketState);
  try {
    window.localStorage.setItem(STORAGE_KEY, market || 'ALL');
  } catch {
    // A storage failure should not prevent the active view from changing.
  }
  marketState.set({ ...current, ready: true, market });
  if (announce) window.dispatchEvent(new CustomEvent('ledger:market-change', { detail: { market } }));
}

export function updateSettings(settings: SettingsResponse) {
  marketState.update((state) => ({ ...state, settings }));
}

export function marketParams(market: MarketSelection, initial?: URLSearchParams) {
  const params = new URLSearchParams(initial);
  if (market) params.set('market', market);
  else params.delete('market');
  return params;
}

export function withMarket(path: string, market: MarketSelection) {
  const url = new URL(path, 'http://ledger.local');
  const params = marketParams(market, url.searchParams);
  const query = params.toString();
  return `${url.pathname}${query ? `?${query}` : ''}${url.hash}`;
}

export function marketLabel(market: MarketSelection) {
  if (market === 'CA') return 'Canada';
  if (market === 'TZ') return 'Tanzania';
  return 'All markets';
}
