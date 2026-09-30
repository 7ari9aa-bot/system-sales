import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useFormatters } from "@/lib/dates";

/** عملاء حقيقيون من GET /customers. بيرجع null أثناء التحميل.
 *  الـbackend مش بينشر قناة/عدد طلبات/آخر ظهور في القائمة — فالمصفوفة
 *  بتعرض اللي موجود فعلًا: الاسم والهاتف وقيمة العميل والحالة. */
export default function useCustomers() {
  const [rows, setRows] = useState(null);
  const { ago } = useFormatters();

  useEffect(() => {
    let alive = true;
    api("/customers?limit=200")
      .then((d) => alive && setRows(d?.items ?? (Array.isArray(d) ? d : [])))
      .catch(() => alive && setRows([]));
    return () => {
      alive = false;
    };
  }, []);

  return useMemo(
    () =>
      rows &&
      rows.map((c) => ({
        id: c.id,
        name: c.name,
        channel: c.channel || "webchat",
        orders: c.orders_count ?? 0,
        spent: Number(c.lifetime_value ?? 0),
        status: c.is_blocked ? "blocked" : Number(c.lifetime_value ?? 0) > 0 ? "active" : "lead",
        lastSeen: c.last_seen_at ? ago(c.last_seen_at) : "—",
      })),
    [rows, ago]
  );
}
