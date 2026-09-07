const CACHE = 'amosclaud-book-v1';
const APP_SHELL = [
  '/static/amosclaud-book.html',
  '/static/amosclaud-book-studio.html',
  '/static/amosclaud-book-offline.js',
  '/static/amosclaud-book-resume.html'
];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  event.respondWith(caches.match(event.request).then(cached => {
    const network = fetch(event.request).then(response => {
      if (response.ok) caches.open(CACHE).then(cache => cache.put(event.request, response.clone()));
      return response;
    }).catch(() => cached || new Response('Amosclaud Book is available offline. Reconnect to load this resource.', {status: 503, headers: {'Content-Type': 'text/plain'}}));
    return cached || network;
  }));
});
