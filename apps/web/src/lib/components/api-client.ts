import { apiMessage } from '$lib/format.js';

export async function readJson<T>(url: string, fallback = 'Ledger data is temporarily unavailable.'): Promise<T> {
  const response = await fetch(url, {
    cache: 'no-store',
    headers: { accept: 'application/json' }
  });
  if (!response.ok) throw new Error(await apiMessage(response, fallback));
  return response.json() as Promise<T>;
}

export async function readOptionalJson<T>(url: string): Promise<T | null> {
  const response = await fetch(url, {
    cache: 'no-store',
    headers: { accept: 'application/json' }
  });
  if (response.status === 404 || response.status === 501) return null;
  if (!response.ok) throw new Error(await apiMessage(response, 'This view is temporarily unavailable.'));
  return response.json() as Promise<T>;
}

export async function sendJson<T>(url: string, method: 'POST' | 'PATCH', body: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { accept: 'application/json', 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error(await apiMessage(response, 'The change could not be saved.'));
  return response.json() as Promise<T>;
}

export function dateTime(value: string | null | undefined) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(parsed);
}
