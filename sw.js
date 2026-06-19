const CACHE = 'psx-tracker-v1';

const RESOURCES = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') {
    return;
  }
  event.respondWith(
    caches.open(CACHE).then((cache) => {
      return cache.match(request).then((response) => {
        const fetchPromise = fetch(request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            cache.put(request, networkResponse.clone());
          }
          return networkResponse;
        }).catch(() => response);
        return response || fetchPromise;
      });
    })
  );
});
