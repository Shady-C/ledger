/// <reference lib="webworker" />

import { build, files, version } from '$service-worker';

const worker = self as unknown as ServiceWorkerGlobalScope;
const shellCache = `ledger-shell-${version}`;
const readCache = `ledger-private-reads-${version}`;
const shell = [...build, ...files];

worker.addEventListener('install', (event) => {
  event.waitUntil(caches.open(shellCache).then((cache) => cache.addAll(shell)));
  worker.skipWaiting();
});

worker.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => ![shellCache, readCache].includes(key)).map((key) => caches.delete(key))))
      .then(() => worker.clients.claim())
  );
});

async function cacheSuccessful(cacheName: string, request: Request, response: Response) {
  if (response.ok) {
    const cache = await caches.open(cacheName);
    await cache.put(request, response.clone());
  }
  return response;
}

async function networkFirst(request: Request, cacheName: string) {
  try {
    const response = await fetch(request);
    return await cacheSuccessful(cacheName, request, response);
  } catch (error) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw error;
  }
}

worker.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== worker.location.origin) return;

  const privateAggregate =
    url.pathname === '/api/accounts' || url.pathname.startsWith('/api/analytics/');
  if (privateAggregate) {
    event.respondWith(networkFirst(request, readCache));
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, shellCache));
    return;
  }

  if (shell.includes(url.pathname)) {
    event.respondWith(caches.match(request).then((cached) => cached ?? fetch(request)));
  }
});
