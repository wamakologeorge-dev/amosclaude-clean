const CACHE_NAME = 'amosclaud-app-v1';
const APP_SHELL = [
  '/login',
  '/static/manifest.webmanifest',
  '/static/amosclaud-app-icon.svg',
  '/static/login.css',
  '/static/login.js',
  '/static/app-install.js'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)).catch(() => undefined));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(async () => {
        const cached = await caches.match('/login');
        return cached || new Response('Amosclaud is offline. Reconnect and try again.', {
          status: 503,
          headers: {'Content-Type': 'text/plain; charset=utf-8'}
        });
      })
    );
    return;
  }

  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
      }
      return response;
    }))
  );
});
