import { useCallback, useEffect, useState } from "react";
import { posApi } from "../api/posApi";
import { countOfflineSales, listOfflineSales, removeOfflineSale } from "./offlineQueue";

export function useOfflineSync({ onSaleSynced, onError } = {}) {
  const [isOnline, setIsOnline] = useState(() => (typeof navigator !== "undefined" ? navigator.onLine : true));
  const [pendingCount, setPendingCount] = useState(0);
  const [isSyncing, setIsSyncing] = useState(false);

  const refreshCount = useCallback(async () => {
    try {
      const c = await countOfflineSales();
      setPendingCount(c);
    } catch {
      // non-fatal
    }
  }, []);

  const syncPending = useCallback(async () => {
    if (isSyncing || !navigator.onLine) return;
    setIsSyncing(true);
    try {
      const pending = await listOfflineSales();
      for (const item of pending) {
        try {
          const { registerId, payload } = item.data;
          // The key stored with the record, never a fresh one: a replay of a sale the server already
          // took must come back as that same sale, not as a second sale.
          const intent = { key: item.intent_key || `pos-${item.id}` };
          const result = await posApi.recordSale(registerId, payload, intent);
          await removeOfflineSale(item.id);
          onSaleSynced?.(result, item);
        } catch (err) {
          onError?.(err, item);
          // If network error occurred again, break early
          if (!navigator.onLine) break;
        }
      }
    } finally {
      setIsSyncing(false);
      await refreshCount();
    }
  }, [isSyncing, onSaleSynced, onError, refreshCount]);

  useEffect(() => {
    refreshCount();

    const handleOnline = () => {
      setIsOnline(true);
      syncPending();
    };
    const handleOffline = () => {
      setIsOnline(false);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [refreshCount, syncPending]);

  return {
    isOnline,
    pendingCount,
    isSyncing,
    refreshCount,
    syncPending,
  };
}
