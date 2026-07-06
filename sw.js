// Service Worker: App-Shell-Cache für Offline-Start.
// Wetterdaten (api.open-meteo.com) werden NIE gecacht – immer live.
const VERSION = "v1";
const SHELL = [
  "./",
  "index.html",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/icon-maskable-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);

  // API- und Font-Requests unangetastet durchlassen
  if (url.origin !== self.location.origin) return;

  // Navigation: network-first, Cache als Offline-Fallback
  if (e.request.mode === "navigate") {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const copy = r.clone();
          caches.open(VERSION).then((c) => c.put("index.html", copy));
          return r;
        })
        .catch(() => caches.match("index.html"))
    );
    return;
  }

  // Statische Shell-Dateien: cache-first, im Hintergrund aktualisieren
  e.respondWith(
    caches.match(e.request).then((cached) => {
      const fresh = fetch(e.request)
        .then((r) => {
          if (r.ok) {
            const copy = r.clone();
            caches.open(VERSION).then((c) => c.put(e.request, copy));
          }
          return r;
        })
        .catch(() => cached);
      return cached || fresh;
    })
  );
});
