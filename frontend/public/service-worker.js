// Keeps the field app openable with no signal.
//
// Scope is deliberately narrow. It caches the application shell — the HTML, JS
// and CSS needed to boot — and nothing else. API responses are NOT cached here:
// business data lives in IndexedDB (see offlineStore.js), where the app controls
// exactly what is stored and how stale it is allowed to be. A cached API
// response would be far more dangerous, since a salesman could unknowingly price
// a sale from yesterday's data.

const CACHE = "erp-field-shell-v1";
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      // Individually, so one missing asset cannot fail the whole install.
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // The API must always hit the network; the app handles failure itself by
  // queueing. Serving a stale API response would silently corrupt a round.
  if (url.pathname.startsWith("/api/")) return;

  // A single-page app: any navigation resolves to the cached shell when the
  // network is gone, so the salesman can still open the app in a dead spot.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match("/index.html").then((r) => r ?? Response.error()))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request)
        .then((response) => {
          if (response.ok && response.type === "basic") {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached ?? Response.error());
    })
  );
});
