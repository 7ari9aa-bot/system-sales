import { useCallback, useEffect, useState } from "react";
import { api, apiCached, peekCache } from "@/lib/api";

const PAGE_SIZE = 100;
const FIRST_PAGE = `/customers?limit=${PAGE_SIZE}`;

/** Real customer list fields only; the API does not expose order counts or activity dates here. */
export default function useCustomers() {
  const [customers, setCustomers] = useState(() => {
    const cached = peekCache(FIRST_PAGE);
    return Array.isArray(cached?.items) ? cached.items : null;
  });
  const [nextCursor, setNextCursor] = useState(() => peekCache(FIRST_PAGE)?.next_cursor ?? null);
  const [loading, setLoading] = useState(customers === null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiCached(FIRST_PAGE, { ttlMs: 0 });
      setCustomers(Array.isArray(data?.items) ? data.items : []);
      setNextCursor(data?.next_cursor ?? null);
    } catch (err) {
      setError(err?.message || "Could not load customers");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setError("");
    try {
      const data = await api(`${FIRST_PAGE}&cursor=${encodeURIComponent(nextCursor)}`);
      setCustomers((current) => [...(current || []), ...(Array.isArray(data?.items) ? data.items : [])]);
      setNextCursor(data?.next_cursor ?? null);
    } catch (err) {
      setError(err?.message || "Could not load more customers");
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, loadingMore]);

  return { customers, loading, loadingMore, nextCursor, loadMore, reload, error };
}
