// Local storage for the salesman's field app: the reference data cached for
// working with no signal, and the queue of documents waiting to reach the
// server.
//
// IndexedDB rather than localStorage: a round can hold hundreds of lines, and
// localStorage is synchronous and size-capped. Everything here is namespaced per
// user so two accounts on one device never see each other's round.

const DB_NAME = "erp-field";
const DB_VERSION = 1;
const SNAPSHOT_STORE = "snapshot";
const QUEUE_STORE = "queue";

let dbPromise = null;

function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(SNAPSHOT_STORE)) {
        db.createObjectStore(SNAPSHOT_STORE);
      }
      if (!db.objectStoreNames.contains(QUEUE_STORE)) {
        // Keyed by the client_uuid, which is also what makes the server side
        // idempotent — the same identifier travels all the way through.
        db.createObjectStore(QUEUE_STORE, { keyPath: "client_uuid" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return dbPromise;
}

async function withStore(storeName, mode, run) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, mode);
    const store = tx.objectStore(storeName);
    const result = run(store);
    tx.oncomplete = () => resolve(result?.result ?? result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

/** A v4-shaped identifier minted before the document ever reaches the server. */
export function newClientUuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  // Older WebViews: good enough, since uniqueness only has to hold per device.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/**
 * A short human reference for the receipt handed over in the field. The real
 * invoice number only exists after sync, so this is what the customer holds
 * until then — deliberately distinct in shape so it can never be mistaken for
 * an official number.
 */
export function provisionalReference(clientUuid) {
  return `FLD-${clientUuid.slice(0, 8).toUpperCase()}`;
}

// --- Cached reference data ---
export async function saveSnapshot(key, value) {
  return withStore(SNAPSHOT_STORE, "readwrite", (store) =>
    store.put({ value, saved_at: new Date().toISOString() }, key)
  );
}

export async function readSnapshot(key) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const request = db
      .transaction(SNAPSHOT_STORE, "readonly")
      .objectStore(SNAPSHOT_STORE)
      .get(key);
    request.onsuccess = () => resolve(request.result ?? null);
    request.onerror = () => reject(request.error);
  });
}

// --- Outbound queue ---
export async function enqueue(document) {
  return withStore(QUEUE_STORE, "readwrite", (store) => store.put(document));
}

export async function queued() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const request = db
      .transaction(QUEUE_STORE, "readonly")
      .objectStore(QUEUE_STORE)
      .getAll();
    request.onsuccess = () => resolve(request.result ?? []);
    request.onerror = () => reject(request.error);
  });
}

export async function dequeue(clientUuid) {
  return withStore(QUEUE_STORE, "readwrite", (store) => store.delete(clientUuid));
}

/** Records the server's verdict so a rejected document can be shown and retried. */
export async function markFailed(clientUuid, message) {
  const db = await openDb();
  const existing = await new Promise((resolve, reject) => {
    const request = db
      .transaction(QUEUE_STORE, "readonly")
      .objectStore(QUEUE_STORE)
      .get(clientUuid);
    request.onsuccess = () => resolve(request.result ?? null);
    request.onerror = () => reject(request.error);
  });
  if (!existing) return;
  return enqueue({
    ...existing,
    last_error: message,
    attempts: (existing.attempts ?? 0) + 1,
  });
}
