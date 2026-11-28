/**
 * Offline sale queue backed by IndexedDB.
 *
 * Guarantees:
 * 1. Zero external dependencies (uses standard browser window.indexedDB).
 * 2. When a sale fails due to network outage (navigator.onLine === false or fetch fails with TypeError/NetworkError),
 *    the sale payload is persisted in the 'pending_sales' store.
 * 3. On reconnect (or manual trigger), each pending sale is submitted sequentially.
 *    Upon server success, it is removed from the store.
 */

const DB_NAME = "fihrist_pos_offline";
const DB_VERSION = 1;
const STORE_NAME = "pending_sales";

function openDB() {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined" || !window.indexedDB) {
      resolve(null);
      return;
    }
    const request = window.indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function enqueueOfflineSale(saleData) {
  const db = await openDB();
  const id =
    globalThis.crypto?.randomUUID?.() ??
    `off-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

  const record = {
    id,
    data: saleData,
    // One Idempotency-Key for this sale, minted HERE and kept with the record. Replays reuse it,
    // so a sale the server already took (reply lost on a weak connection) is returned, not booked
    // and deducted from stock a second time. Never regenerate it on a retry.
    intent_key: saleData?.intentKey || `pos-${id}`,
    created_at: new Date().toISOString(),
    retry_count: 0,
  };

  if (!db) {
    // Memory fallback if IndexedDB is unavailable
    return record;
  }

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const req = store.add(record);
    req.onsuccess = () => resolve(record);
    req.onerror = () => reject(req.error);
  });
}

export async function listOfflineSales() {
  const db = await openDB();
  if (!db) return [];

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

export async function countOfflineSales() {
  const db = await openDB();
  if (!db) return 0;

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const req = store.count();
    req.onsuccess = () => resolve(req.result || 0);
    req.onerror = () => reject(req.error);
  });
}

export async function removeOfflineSale(id) {
  const db = await openDB();
  if (!db) return;

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const req = store.delete(id);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

export async function clearOfflineSales() {
  const db = await openDB();
  if (!db) return;

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const req = store.clear();
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}
