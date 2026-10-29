// Stomped service worker: keeps a copy of the app on the phone so it opens with no signal.
//
// - The app page itself: try the network first (so updates arrive), fall back to the saved copy.
// - Code libraries and fonts from CDNs: use the saved copy (they never change at a given version).
// - Database calls and videos (Supabase): never cached. They always go to the network.
// - Clips waiting for signal (outbox.js): when the signal comes back the browser wakes this worker (Android), and it
//   hands the upload to the open app, or does it itself if the app is closed.

importScripts('outbox.js');

const CACHE = 'sendit-v3';   // v3: the 10/28 rebrand (new icons) + outbox.js
const SHELL = ['./', './outbox.js', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png', './icons/apple-touch-icon.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.hostname.endsWith('supabase.co') || url.hostname.endsWith('open-meteo.com')) return;  // live data only

  const isLibrary = /cdn\.jsdelivr\.net|fonts\.googleapis\.com|fonts\.gstatic\.com/.test(url.hostname);
  if (isLibrary){
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
      const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); return res;
    })));
    return;
  }
  if (url.origin === location.origin){
    // no-cache: ask GitHub every time (it otherwise lets phones reuse the page for 10 min, so a push looked missing)
    e.respondWith(fetch(req, {cache: 'no-cache'}).then(res => {
      if (res.ok){ const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req).then(hit => hit || caches.match('./'))));
  }
});

// Signal is back (Background Sync). The visible app uploads (it can renew the login); with the app closed or hidden,
// this worker uploads with the saved login, if it has time left. If clips are still waiting, failing here makes the
// browser try again later; and the app retries on open either way.
self.addEventListener('sync', e => {
  if (e.tag !== StompedOutbox.SYNC_TAG) return;
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({type: 'window'});
    const open = wins.filter(w => w.visibilityState === 'visible');
    if (open.length){ open.forEach(w => w.postMessage({type: 'outbox-flush'})); return; }
    const a = await StompedOutbox.getAuth();
    if (!a || !a.token || (a.exp || 0) * 1000 < Date.now() + 120000) return;   // no login with time left: wait for the app
    const api = {url: a.url, key: a.key, token: async () => a.token};
    const r = await StompedOutbox.flush({api, uid: a.uid, force: true});
    wins.forEach(w => w.postMessage({type: 'outbox-changed', sent: r.sent.length}));
    if (r.waiting) throw new Error('still waiting for signal');
  })());
});
