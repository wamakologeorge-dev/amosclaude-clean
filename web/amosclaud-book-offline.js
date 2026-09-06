/* Amosclaud Book local-first storage. No credentials are stored here. */
(function (global) {
  'use strict';
  const DB_NAME = 'amosclaud-book';
  const DB_VERSION = 1;
  const STORES = { docs: 'documents', queue: 'sync_queue', meta: 'meta' };
  const api = global.AmosclaudBookOffline = {};

  function openDb() {
    return new Promise((resolve, reject) => {
      if (!('indexedDB' in global)) return reject(new Error('IndexedDB is unavailable'));
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORES.docs)) {
          const s = db.createObjectStore(STORES.docs, { keyPath: 'id' });
          s.createIndex('updatedAt', 'updatedAt');
          s.createIndex('kind', 'kind');
        }
        if (!db.objectStoreNames.contains(STORES.queue)) {
          const s = db.createObjectStore(STORES.queue, { keyPath: 'id', autoIncrement: true });
          s.createIndex('status', 'status');
          s.createIndex('createdAt', 'createdAt');
        }
        if (!db.objectStoreNames.contains(STORES.meta)) db.createObjectStore(STORES.meta, { keyPath: 'key' });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error('IndexedDB open failed'));
    });
  }

  function tx(store, mode, fn) {
    return openDb().then(db => new Promise((resolve, reject) => {
      const t = db.transaction(store, mode);
      let result;
      try { result = fn(t.objectStore(store)); } catch (e) { reject(e); return; }
      t.oncomplete = () => resolve(result);
      t.onerror = () => reject(t.error || new Error('IndexedDB transaction failed'));
      t.onabort = () => reject(t.error || new Error('IndexedDB transaction aborted'));
    }));
  }

  const now = () => new Date().toISOString();
  const uid = prefix => `${prefix}-${crypto.randomUUID ? crypto.randomUUID() : Date.now() + '-' + Math.random().toString(16).slice(2)}`;

  api.saveDocument = async function (doc) {
    const record = Object.assign({ id: uid('book'), kind: 'book', title: 'Untitled', content: '', version: 1 }, doc, {
      updatedAt: now(), localOnly: true
    });
    await tx(STORES.docs, 'readwrite', s => s.put(record));
    await tx(STORES.queue, 'readwrite', s => s.add({
      operationId: uid('op'), documentId: record.id, operation: 'upsert', payload: record,
      createdAt: now(), status: 'pending', attempts: 0
    }));
    return record;
  };

  api.getDocument = id => tx(STORES.docs, 'readonly', s => new Promise((resolve, reject) => {
    const r = s.get(id); r.onsuccess = () => resolve(r.result || null); r.onerror = () => reject(r.error);
  }));

  api.listDocuments = () => tx(STORES.docs, 'readonly', s => new Promise((resolve, reject) => {
    const r = s.getAll(); r.onsuccess = () => resolve((r.result || []).sort((a,b) => String(b.updatedAt).localeCompare(String(a.updatedAt)))); r.onerror = () => reject(r.error);
  }));

  api.deleteDocument = async id => {
    await tx(STORES.docs, 'readwrite', s => s.delete(id));
    await tx(STORES.queue, 'readwrite', s => s.add({ operationId: uid('op'), documentId: id, operation: 'delete', createdAt: now(), status: 'pending', attempts: 0 }));
  };

  api.pending = () => tx(STORES.queue, 'readonly', s => new Promise((resolve, reject) => {
    const r = s.index('status').getAll('pending'); r.onsuccess = () => resolve(r.result || []); r.onerror = () => reject(r.error);
  }));

  api.markSynced = id => tx(STORES.queue, 'readwrite', s => s.delete(id));
  api.markConflict = (id, reason) => tx(STORES.queue, 'readwrite', s => {
    const r = s.get(id); r.onsuccess = () => { const item = r.result; if (!item) return; item.status='conflict'; item.reason=reason || 'Server changed since local edit'; item.updatedAt=now(); s.put(item); };
  });

  api.sync = async function (endpoint) {
    if (!navigator.onLine) return { online: false, synced: 0, conflicts: 0, pending: (await api.pending()).length };
    const items = await api.pending();
    let synced = 0, conflicts = 0;
    for (const item of items) {
      try {
        const response = await fetch(endpoint || '/api/v1/book/offline-sync', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
          body: JSON.stringify(item)
        });
        if (response.status === 409) { conflicts++; await api.markConflict(item.id, 'Remote version differs; review before replacing either copy.'); continue; }
        if (!response.ok) throw new Error(`sync HTTP ${response.status}`);
        await api.markSynced(item.id); synced++;
      } catch (error) {
        console.warn('Amosclaud Book sync deferred:', error);
        break;
      }
    }
    return { online: true, synced, conflicts, pending: (await api.pending()).length };
  };

  api.status = async () => ({ online: navigator.onLine, pending: (await api.pending()).length });
  global.addEventListener('online', () => api.sync().catch(console.warn));
  global.addEventListener('offline', () => global.dispatchEvent(new CustomEvent('amosclaud-book-offline')));
})(window);
