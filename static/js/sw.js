const CACHE_NAME = 'apotek-k24-v3';
const urlsToCache = [
  '/',
  '/login',
  '/manifest.json',
  '/static/sounds/urgent-alert.wav',
  '/static/img/apotek-icon-192.png',
  '/static/img/apotek-icon-512.png',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(cacheNames => Promise.all(
        cacheNames.map(cache => {
          if (cache !== CACHE_NAME) {
            return caches.delete(cache);
          }
          return null;
        })
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  if (event.request.url.includes('/api/stream')) return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response.status === 200) {
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, responseToCache));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

self.addEventListener('message', event => {
  const payload = event.data || {};
  if (payload.type !== 'SHOW_NOTIFICATION') return;

  event.waitUntil(
    self.registration.showNotification(payload.title || 'Pesan Urgent!', {
      body: payload.body || 'Ada pesan baru',
      icon: '/static/img/apotek-icon-192.png',
      badge: '/static/img/apotek-icon-192.png',
      vibrate: [200, 100, 200, 100, 200],
      tag: payload.tag || 'urgent-message',
      renotify: true,
      requireInteraction: true,
      data: {
        url: payload.url || '/messages/queue',
        timestamp: Date.now(),
      },
      actions: [
        { action: 'open', title: 'Buka Dashboard' },
        { action: 'close', title: 'Tutup' },
      ],
    })
  );
});

self.addEventListener('push', event => {
  let data = { title: 'Pesan Urgent!', body: 'Ada pesan baru' };

  if (event.data) {
    try {
      data = event.data.json();
    } catch (err) {
      data.body = event.data.text();
    }
  }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/img/apotek-icon-192.png',
      badge: '/static/img/apotek-icon-192.png',
      vibrate: [200, 100, 200, 100, 200],
      tag: 'urgent-message',
      renotify: true,
      requireInteraction: true,
      data: {
        url: data.url || '/messages/queue',
        timestamp: Date.now(),
      },
      actions: [
        { action: 'open', title: 'Buka Dashboard' },
        { action: 'close', title: 'Tutup' },
      ],
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  if (event.action === 'close') return;

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      const targetUrl = event.notification.data?.url || '/';

      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }

      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }

      return null;
    })
  );
});
