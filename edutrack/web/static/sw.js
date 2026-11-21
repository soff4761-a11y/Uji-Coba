/* EduTrack Progressive Web App Service Worker (App Shell Offline Cache v7 ES Modules) */
const CACHE_NAME = "edutrack-shell-v8.4.2";
const APP_SHELL = [
  "/",
  "/manifest.json",
  "/static/icon.svg",
  "/static/styles.css?v=20261120-v8.4.2",
  "/static/app.js?v=20261120-v8.4.2",
  "/static/js/state.js?v=20261120-v8.4.2",
  "/static/js/api.js?v=20261120-v8.4.2",
  "/static/js/charts.js?v=20261120-v8.4.2",
  "/static/js/teacher.js?v=20261120-v8.4.2",
  "/static/js/student.js?v=20261120-v8.4.2",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;
  if (req.headers.has("Authorization")) return;

  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req).then((cached) => cached || caches.match("/")))
  );
});
