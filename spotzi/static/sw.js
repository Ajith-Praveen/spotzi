const CACHE = "spotzi-shell-v14";
// Application shell only. Case data, evidence, decisions and tokens are never cached (idea/23).
const SHELL = ["/app", "/static/styles.css", "/static/app.js", "/manifest.webmanifest", "/spotzi-icon.svg", "/static/logo-192.png"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
  // take over immediately: this worker is network-first, so it can never pin an outdated app
  self.skipWaiting();
});

self.addEventListener("message", event => {
  if (event.data === "skipWaiting") self.skipWaiting();
  if (event.data === "clearCaches") caches.keys().then(keys => keys.forEach(k => caches.delete(k)));
});

self.addEventListener("activate", event => {
  // remove every older cache, including the first cache-first worker that could serve a stale app
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return; // API: network only
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match(url.pathname === "/" ? "/" : "/app")));
    return;
  }
  event.respondWith(fetch(event.request).then(response => {
    if (response.ok && SHELL.includes(url.pathname)) caches.open(CACHE).then(cache => cache.put(event.request, response.clone()));
    return response;
  }).catch(() => caches.match(event.request)));
});
