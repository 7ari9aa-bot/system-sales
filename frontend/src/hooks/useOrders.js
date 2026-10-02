import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useFormatters } from "@/lib/dates";

const PAGE_SIZE = 100;

/** Orders use the backend cursor contract. The list intentionally exposes only
 * fields the route returns; channel and item counts come from order detail and
 * are not fabricated for the summary table. */
export default function useOrders() {
  const [rows, setRows] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [customerError, setCustomerError] = useState("");
  const [nextCursor, setNextCursor] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [reloadAttempt, setReloadAttempt] = useState(0);
  const { day } = useFormatters();

  const reload = useCallback(() => {
    setError(null);
    setReloadAttempt((attempt) => attempt + 1);
  }, []);

  useEffect(() => {
    let alive = true;
    setError(null);
    Promise.allSettled([
      api(`/orders?limit=${PAGE_SIZE}`),
      api("/customers?limit=200"),
    ]).then(([ordersResult, customersResult]) => {
      if (!alive) return;
      if (ordersResult.status === "rejected") {
        setError(ordersResult.reason?.message || "Could not load orders.");
      } else {
        const ordersResponse = ordersResult.value;
        if (!Array.isArray(ordersResponse?.items)) {
          setError("The server returned an invalid order list.");
        } else {
          setRows(ordersResponse.items);
          setNextCursor(ordersResponse.next_cursor || null);
          setError(null);
        }
      }

      if (customersResult.status === "rejected") {
        setCustomers([]);
        setCustomerError(customersResult.reason?.message || "Could not load customer names.");
      } else {
        setCustomers(Array.isArray(customersResult.value?.items) ? customersResult.value.items : []);
        setCustomerError("");
      }
    });
    return () => { alive = false; };
  }, [reloadAttempt]);

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), cursor: nextCursor });
      const response = await api(`/orders?${params.toString()}`);
      setRows((previous) => [...(previous || []), ...(response?.items || [])]);
      setNextCursor(response?.next_cursor || null);
    } catch (e) {
      setError(e?.message || "Could not load more orders.");
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, loadingMore]);

  const orders = useMemo(() => rows?.map((order) => {
    const customer = customers.find((candidate) => candidate.id === order.customer_id);
    return {
      id: order.number ?? order.id,
      recordId: order.id,
      customer: customer?.name ?? order.customer_id ?? "—",
      customerId: order.customer_id,
      total: Number(order.grand_total ?? 0),
      currency: order.currency,
      status: order.status || "—",
      date: day(order.placed_at || order.created_at),
      createdAt: order.created_at,
    };
  }) ?? null, [rows, customers, day]);

  return {
    orders,
    loading: rows === null && !error,
    loadingMore,
    nextCursor,
    loadMore,
    reload,
    error,
    customerError,
  };
}
