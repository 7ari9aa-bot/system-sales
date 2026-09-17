"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/t";

type Order = {
  id: string;
  number: string;
  customer_id: string;
  status: string;
  grand_total: string;
  currency: string;
  placed_at: string | null;
  created_at: string;
};

const STATUS_BADGE: Record<string, string> = {
  pending: "badge-warning",
  confirmed: "badge-primary",
  processing: "badge-primary",
  shipped: "badge-primary",
  delivered: "badge-success",
  completed: "badge-success",
  cancelled: "badge-danger",
  refunded: "badge-danger",
};

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setOrders(await api<Order[]>("/orders"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <h1 className="page-title">{t.orders}</h1>
      {error && <p className="error-text">{error}</p>}
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>{t.orderNumber}</th>
              <th>{t.customer}</th>
              <th>{t.grandTotal}</th>
              <th>{t.status}</th>
              <th>{t.date}</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td dir="ltr">{o.number}</td>
                <td dir="ltr" style={{ fontSize: 12 }}>{o.customer_id.slice(0, 8)}…</td>
                <td dir="ltr">
                  {Number(o.grand_total).toFixed(2)} {o.currency}
                </td>
                <td>
                  <span className={`badge ${STATUS_BADGE[o.status] ?? ""}`}>{o.status}</span>
                </td>
                <td dir="ltr" style={{ fontSize: 12 }}>
                  {new Date(o.placed_at ?? o.created_at).toLocaleDateString("ar-EG-u-nu-latn")}
                </td>
              </tr>
            ))}
            {orders.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">
                  لا توجد طلبات
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
