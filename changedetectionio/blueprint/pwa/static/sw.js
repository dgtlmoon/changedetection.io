// changedetection.io service worker.
//
// This exists for ONE reason: Android only registers a Web Share Target for a real WebAPK,
// and Chrome's criteria for offering "Install" (rather than the shortcut that isn't a WebAPK
// and never reaches the share sheet) have wanted a service worker with a fetch handler. A
// user typically tries sharing exactly once, so the cost of being wrong here is the whole
// feature, and ten lines of no-op worker is cheap insurance.
//
// It deliberately CACHES NOTHING. Static assets already get fingerprinted ?v= URLs with
// immutable Cache-Control, so a caching layer here would add no speed - only the risk of
// serving a stale page with a dead CSRF token, from a cache the operator can't clear
// remotely. See test_cache_control_headers.py for what that failure looks like.
//
// Only navigations are intercepted, and only to pass them straight through. Leaving assets,
// range requests, Socket.IO and EventSource untouched keeps navigation preload and streaming
// working exactly as they do without a worker.

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request));
  }
});
