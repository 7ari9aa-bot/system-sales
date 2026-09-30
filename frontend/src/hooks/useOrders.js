import { useEffect, useMemo, useState } from "react";
import { apiCached, peekCache } from "@/lib/api";
import { useFormatters } from "@/lib/dates";

/** طلبات حقيقية من GET /orders، مع ربط اسم العميل من /customers.
 *  بيرجع null أثناء التحميل. المبلغ نص من الـbackend (ADR) بيتحول
 *  للعرض فقط — الطباعة بتقرب على نفس القيمة اللي جاية. */
export default function useOrders() {
  const [rows, setRows] = useState(null);
  const [customers, setCustomers] = useState([]);
  const { day } = useFormatters();

  useEffect(() => {
    let alive = true;
    const cached = peekCache("/orders?limit=200");
    if (cached) setRows(cached?.items ?? (Array.isArray(cached) ? cached : []));
    const cachedC = peekCache("/customers?limit=200");
    if (cachedC) setCustomers(cachedC?.items ?? (Array.isArray(cachedC) ? cachedC : []));
    apiCached("/orders?limit=200")
      .then((d) => alive && setRows(d?.items ?? (Array.isArray(d) ? d : [])))
      .catch(() => alive && setRows([]));
    apiCached("/customers?limit=200")
      .then((d) => alive && setCustomers(d?.items ?? (Array.isArray(d) ? d : [])))
      .catch(() => alive && setCustomers([]));
    return () => {
      alive = false;
    };
  }, []);

  return useMemo(
    () =>
      rows &&
      rows.map((o) => {
        const c = customers.find((x) => x.id === o.customer_id);
        return {
          id: o.number ?? o.id,
          customer: c?.name ?? o.customer_id ?? "—",
          channel: o.channel || "webchat",
          items: o.items_count ?? 0,
          total: Number(o.grand_total ?? 0),
          status: o.status || "processing",
          date: day(o.placed_at || o.created_at),
        };
      }),
    [rows, customers, day]
  );
}
