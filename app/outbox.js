// Stomped outbox: mountain-proof uploads. Shared by the app page and the service worker (sw.js).
//
// Every filmed clip is saved on the phone first (IndexedDB, the browser's own storage) and only then uploaded.
// With no signal it waits and retries with backoff (5 s, 10 s, 20 s ... up to 5 min), when the signal comes back,
// when the app is opened again, and (Android) from the service worker even while the app is closed.
// A clip leaves the phone's storage only once the server has it. Nothing here ever deletes a clip because of an error:
// a clip the server refuses is marked "stuck" and waits for the rider to retry, save it, or delete it.
//
// Each upload is steps that are saved as they finish (video uploaded -> clip row made -> duel move sent), so a retry
// after a dropped connection picks up where it stopped instead of posting the same clip twice.
(function (root){
  const DB_NAME = 'sendit', DB_VER = 2, ITEMS = 'outbox', META = 'meta';
  const BUCKET = 'clips', SYNC_TAG = 'stomped-outbox';
  const MAX_WAIT = 5 * 60 * 1000;   // longest gap between automatic retries

  // ---------- storage ----------
  let dbp = null;
  function openDb(){
    if (dbp) return dbp;
    dbp = new Promise((res, rej) => {
      const r = indexedDB.open(DB_NAME, DB_VER);
      r.onupgradeneeded = () => {
        const d = r.result;   // v1 had only the outbox store; its old items still upload (they get a path on first try)
        if (!d.objectStoreNames.contains(ITEMS)) d.createObjectStore(ITEMS, {keyPath: 'id'});
        if (!d.objectStoreNames.contains(META)) d.createObjectStore(META);
      };
      r.onsuccess = () => {
        const d = r.result;
        d.onversionchange = () => { d.close(); dbp = null; };   // a newer app version wants to upgrade: step aside
        res(d);
      };
      r.onerror = () => { dbp = null; rej(r.error); };
      r.onblocked = () => { dbp = null; rej(new Error('storage busy')); };
    });
    return dbp;
  }
  async function run(store, mode, fn){
    const d = await openDb();
    return new Promise((res, rej) => {
      const t = d.transaction(store, mode), req = fn(t.objectStore(store));
      t.oncomplete = () => res(req && req.result); t.onerror = () => rej(t.error); t.onabort = () => rej(t.error);
    });
  }
  const put = item => run(ITEMS, 'readwrite', s => s.put(item));
  const get = id => run(ITEMS, 'readonly', s => s.get(id));
  const all = () => run(ITEMS, 'readonly', s => s.getAll());
  const remove = id => run(ITEMS, 'readwrite', s => s.delete(id));
  const setMeta = (k, v) => run(META, 'readwrite', s => v == null ? s.delete(k) : s.put(v, k));
  const getMeta = k => run(META, 'readonly', s => s.get(k));

  // Take an item for uploading. The page and the service worker can both be awake, so this checks and sets a
  // short lock in one transaction: only one of them uploads a clip at a time.
  async function claim(id, ms){
    const d = await openDb();
    return new Promise((res, rej) => {
      const t = d.transaction(ITEMS, 'readwrite'), s = t.objectStore(ITEMS);
      let got = null;
      const r = s.get(id);
      r.onsuccess = () => {
        const it = r.result;
        if (!it || (it.lockedUntil || 0) > Date.now()) return;
        it.lockedUntil = Date.now() + ms; got = it; s.put(it);
      };
      t.oncomplete = () => res(got); t.onerror = () => rej(t.error);
    });
  }

  // Ask the browser not to clear our storage when the phone is low on space (iPhones clear unused site data).
  function keepStorage(){
    try { if (root.navigator && navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {}); } catch (e) {}
  }

  // ---------- items ----------
  // kind 'draft': filmed, not posted yet (kept so closing the app doesn't lose it). 'post' / 'duel': waiting to upload.
  async function save(item){
    const it = {createdAt: Date.now(), attempts: 0, nextTry: 0, ...item};
    if (!it.id) it.id = crypto.randomUUID();
    await put(it); keepStorage();
    return it;
  }
  async function waiting(uid){
    return (await all()).filter(i => i.kind !== 'draft' && (!uid || !i.uid || i.uid === uid))
      .sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0));
  }
  async function draft(uid){ return (await all()).find(i => i.kind === 'draft' && i.uid === uid) || null; }
  async function clearDrafts(uid, keepId){
    for (const i of await all()) if (i.kind === 'draft' && i.uid === uid && i.id !== keepId) await remove(i.id);
  }

  // ---------- retry plan ----------
  // 5 s, 10 s, 20 s, 40 s ... capped at 5 min, with a little randomness so a lift line of phones doesn't retry in sync.
  function backoff(attempts){
    const base = Math.min(MAX_WAIT, 5000 * Math.pow(2, Math.max(0, attempts - 1)));
    return Math.round(base * (0.8 + Math.random() * 0.4));
  }
  // How long to give one upload before calling it a dropped connection: 30 s plus time at a slow 32 KB/s.
  const uploadTimeout = bytes => 30000 + Math.ceil((bytes || 0) / 32768) * 1000;

  // Errors that mean "try again later" (no signal, timeout, server busy, login expired) vs. "the server said no".
  function isTransient(err){
    if (!err) return false;
    if (err.offline || err.auth) return true;
    const s = err.status || 0;
    return s === 0 || s === 401 || s === 408 || s === 425 || s === 429 || s >= 500;
  }

  // ---------- server calls (plain fetch, so the service worker can make them too) ----------
  function netError(msg){ const e = new Error(msg || 'No signal'); e.offline = true; return e; }
  function httpError(status, data){
    const msg = (data && (data.message || data.error_description || data.error)) || (typeof data === 'string' && data) || `HTTP ${status}`;
    const e = new Error(String(msg)); e.status = status;
    if (data && data.statusCode) e.code = String(data.statusCode);
    if (/jwt|token.*expired|expired.*token|invalid.*signature/i.test(e.message)) e.auth = true;
    return e;
  }
  async function call(api, method, path, {body, headers = {}, timeout = 30000} = {}){
    const once = async token => {
      const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), timeout);
      try {
        return await fetch(api.url + path, {method, body, signal: ctl.signal,
          headers: {apikey: api.key, Authorization: 'Bearer ' + token, ...headers}});
      } catch (e){
        throw netError(e && e.name === 'AbortError' ? 'Upload timed out' : 'No signal');
      } finally { clearTimeout(t); }
    };
    let res = await once(await api.token());
    let text = await res.text().catch(() => ''), data;
    try { data = text ? JSON.parse(text) : null; } catch (e){ data = text; }
    if (!res.ok){
      const err = httpError(res.status, data);
      if ((res.status === 401 || err.auth) && api.refresh){   // the login ran out while waiting for signal: renew once
        const fresh = await api.refresh().catch(() => null);
        if (fresh){
          res = await once(fresh); text = await res.text().catch(() => '');
          try { data = text ? JSON.parse(text) : null; } catch (e){ data = text; }
          if (res.ok) return data;
          throw httpError(res.status, data);
        }
      }
      throw err;
    }
    return data;
  }
  const json = (body, extra = {}) => ({body: JSON.stringify(body), headers: {'Content-Type': 'application/json', ...extra}});
  const extOf = type => /mp4/.test(type) ? 'mp4' : /quicktime/.test(type) ? 'mov' : 'webm';
  const motionPath = videoPath => videoPath.replace(/\.[^./]+$/, '.motion.json');
  const alreadyThere = e => e.status === 409 || e.code === '409' || /already exists|duplicate/i.test(e.message);

  // Upload one item, resuming from its last finished step. Throws on failure (the item keeps its progress).
  async function send(it, api){
    const step = patch => { Object.assign(it, patch); return it.memory ? null : put(it); };   // memory: phone storage is off
    if (!it.path) await step({path: `${it.uid}/${crypto.randomUUID()}.${extOf(it.blob.type || 'video/webm')}`});
    if (!it.uploaded){
      try {
        await call(api, 'POST', `/storage/v1/object/${BUCKET}/${it.path}`, {body: it.blob, timeout: uploadTimeout(it.blob.size),
          headers: {'Content-Type': it.blob.type || 'video/webm', 'x-upsert': 'false', 'cache-control': '3600'}});
      } catch (e){ if (!alreadyThere(e)) throw e; }   // an earlier try got through before the signal dropped
      await step({uploaded: true});
    }
    if (!it.clipId){
      let clipId = null;
      if (it.triedInsert){   // the last try may have made the clip and lost the answer: look before posting twice
        const found = await call(api, 'GET', `/rest/v1/clips?video_path=eq.${encodeURIComponent(it.path)}&select=id&limit=1`);
        clipId = found && found[0] && found[0].id;
      }
      if (!clipId){
        await step({triedInsert: true});
        const {rider, ...cols} = it.fields;
        if (rider){   // filmed a friend: the database checks you're friends and files it under them (017)
          clipId = await call(api, 'POST', '/rest/v1/rpc/post_for_friend', json({p_rider: rider, p_trick: cols.trick_id,
            p_grab: cols.grab, p_resort: cols.resort, p_video_path: it.path, p_combo: cols.combo || []}));
        } else {
          const row = await call(api, 'POST', '/rest/v1/clips?select=id', json({...cols, video_path: it.path},
            {Prefer: 'return=representation', Accept: 'application/vnd.pgrst.object+json'}));
          clipId = row && row.id;
        }
      }
      await step({clipId});
      // The motion log sits next to the video. Best effort: the clip is posted either way.
      if (it.motion) await call(api, 'POST', `/storage/v1/object/${BUCKET}/${motionPath(it.path)}`,
        {body: JSON.stringify(it.motion), headers: {'Content-Type': 'application/json'}}).catch(() => {});
    }
    if (it.kind === 'duel' && !it.moved){
      try {
        await call(api, 'POST', '/rest/v1/rpc/duel_move', json({p_duel: it.duelId, p_landed: true, p_trick: it.trick || null, p_clip: it.clipId}));
      } catch (e){
        if (isTransient(e)) throw e;
        it.duelError = e.message;   // e.g. the duel moved on: the clip itself is posted, so it isn't lost
      }
      await step({moved: true});
    }
    return it;
  }

  // ---------- flush: upload everything that's due ----------
  // opts: {api, uid, force (ignore the backoff wait), first (id to try first), only (just that one), onStart(it)}
  // Returns {sent: [items], failed: [items the server refused this time], waiting, stuck, nextTry}. Runs one at a time; a call made while one runs waits its turn.
  let chain = Promise.resolve();
  function flush(opts){
    const p = chain.then(() => flushNow(opts));
    chain = p.catch(() => {});
    return p;
  }
  async function flushNow({api, uid, force = false, first = null, only = false, onStart} = {}){
    const out = {sent: [], failed: [], waiting: 0, stuck: 0, nextTry: 0};
    let list = await waiting(uid);
    if (first) list = only ? list.filter(i => i.id === first) : [...list.filter(i => i.id === first), ...list.filter(i => i.id !== first)];
    let noSignal = false;
    for (const i of list){
      if (i.stuck){ out.stuck++; continue; }
      if (noSignal || (!force && (i.nextTry || 0) > Date.now())){ out.waiting++; continue; }
      const it = await claim(i.id, uploadTimeout(i.blob && i.blob.size) + 60000);
      if (!it){ out.waiting++; continue; }   // the other side (page or service worker) is uploading it right now
      it.uid = it.uid || uid;
      try {
        if (onStart) onStart(it, out.sent.length);
        await send(it, api);
        await remove(it.id);
        out.sent.push(it);
      } catch (err){
        it.lockedUntil = 0; it.lastError = err.message;
        if (isTransient(err)){
          it.attempts = (it.attempts || 0) + 1; it.nextTry = Date.now() + backoff(it.attempts);
          noSignal = true; out.waiting++;   // no point trying the rest right now
        } else { it.stuck = true; out.stuck++; out.failed.push(it); }
        await put(it);
      }
    }
    const due = (await waiting(uid)).filter(i => !i.stuck).map(i => i.nextTry || 0);
    out.nextTry = due.length ? Math.min(...due) : 0;
    return out;
  }

  // Wake the service worker when the signal comes back, even if the app was closed (Android Chrome; iPhones retry on open).
  function requestSync(){
    try {
      if (root.navigator && navigator.serviceWorker) navigator.serviceWorker.ready
        .then(r => r.sync && r.sync.register(SYNC_TAG)).catch(() => {});
    } catch (e) {}
  }

  // ---------- smaller uploads when it's safe ----------
  // Weak signal, a low battery (cold kills them fast) or clips already waiting for signal: record at a lower bitrate,
  // and on a low battery at 30 fps (less work for the phone). Still 720p, which the trick AI and judges need.
  const NORMAL = {bps: 1500000, fps: 60, lite: false};
  function planFor({battery, connection, waiting: queued = 0, online = true} = {}){
    const why = [];
    const c = connection || {};
    if (!online) why.push('offline');
    if (queued > 0) why.push('clips waiting');
    if (c.saveData) why.push('data saver');
    if (/(^|-)2g|^3g$/.test(c.effectiveType || '')) why.push('weak signal');
    else if (c.downlink && c.downlink < 1.5) why.push('weak signal');
    const lowBattery = battery && !battery.charging && battery.level <= 0.25;
    if (lowBattery) why.push('low battery');
    if (!why.length) return {...NORMAL, why};
    return {bps: 900000, fps: lowBattery ? 30 : 60, lite: true, why};
  }
  async function shrinkPlan(uid){
    let battery = null, queued = 0;
    try { if (navigator.getBattery) battery = await Promise.race([navigator.getBattery(), new Promise(r => setTimeout(r, 300))]); } catch (e) {}
    try { queued = (await waiting(uid)).filter(i => !i.stuck).length; } catch (e) {}
    return planFor({battery, connection: navigator.connection, waiting: queued, online: navigator.onLine});
  }

  // ---------- the login the service worker uses ----------
  // The page keeps a copy of the current login here, so the service worker can upload while the app is closed.
  // The service worker never renews it (that would sign the page out); it only uses one with time left.
  const setAuth = a => setMeta('auth', a);
  const getAuth = () => getMeta('auth');

  root.StompedOutbox = {SYNC_TAG, save, get, put, remove, all, waiting, draft, clearDrafts, flush, send, claim,
    backoff, uploadTimeout, isTransient, requestSync, planFor, shrinkPlan, setAuth, getAuth, motionPath};
})(self);
