// Service Worker: App-Shell-Cache für Offline-Start.
// Wetterdaten (api.open-meteo.com) werden NIE gecacht – immer live.
const VERSION = "v6";
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
      // Altlast aufräumen: Push-Subscriptions aus der früheren Notification-Version
      // abmelden – es gibt keinen Absender mehr.
      .then(() => self.registration.pushManager.getSubscription())
      .then((sub) => sub && sub.unsubscribe())
      .catch(() => {})
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

  // Messwerte: network-first. Cache-first würde hier dauerhaft eine alte
  // Messung ausliefern und die ganze Live-Anzeige wertlos machen. Der Cache
  // dient nur als Offline-Rückfall – die Anzeige weist Alter selbst aus.
  if (url.pathname.includes("/data/")) {
    // Die App hängt einen Cache-Buster an (?t=…), damit auch ohne aktiven
    // Service Worker nichts Altes aus dem HTTP-Cache kommt (Pages liefert
    // max-age=600). Als Cache-Schlüssel muss die Query aber weg: sonst legt
    // jeder Abruf einen neuen Eintrag an, der Cache wächst unbegrenzt und der
    // Offline-Rückfall trifft nie den zuletzt gespeicherten Stand.
    const key = url.origin + url.pathname;
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          if (r.ok) {
            const copy = r.clone();
            caches.open(VERSION).then((c) => c.put(key, copy));
          }
          return r;
        })
        .catch(() => caches.match(key))
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
