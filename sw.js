/*
 * Service worker: precache the app shell so the daily step works offline.
 * All user data lives in localStorage, so caching the static assets is the
 * whole offline story. Bump CACHE when shipping asset changes.
 */
var CACHE = 'bdss-v1';
var ASSETS = [
  './',
  './index.html',
  './styles.css',
  './manifest.webmanifest',
  './js/tasks.js',
  './js/store.js',
  './js/app.js',
  './icons/icon.svg',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-512-maskable.png',
  './icons/apple-touch-icon.png',
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(ASSETS);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) {
        return k !== CACHE;
      }).map(function (k) {
        return caches.delete(k);
      }));
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then(function (hit) {
      if (hit) return hit;
      return fetch(e.request).then(function (res) {
        // Cache same-origin successful responses for future offline use.
        if (res.ok && new URL(e.request.url).origin === self.location.origin) {
          var copy = res.clone();
          caches.open(CACHE).then(function (cache) {
            cache.put(e.request, copy);
          });
        }
        return res;
      }).catch(function () {
        // Offline navigation fallback: serve the app shell.
        if (e.request.mode === 'navigate') {
          return caches.match('./index.html');
        }
        throw new Error('offline and not cached: ' + e.request.url);
      });
    })
  );
});
