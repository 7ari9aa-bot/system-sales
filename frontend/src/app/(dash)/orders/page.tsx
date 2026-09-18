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

type Product = {
  id: string;
  title: string;
  variants?: { id: string; title: string | null; sku: string | null; price: string }[];
};

type Customer = { id: string; name: string; phone: string | null };

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

type Line = { variant_id: string; quantity: number };

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [lines, setLines] = useState<Line[]>([{ variant_id: "", quantity: 1 }]);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    try {
      const [o, p, c] = await Promise.all([
        api<Order[]>("/orders"),
        api<Product[]>("/products"),
        api<Customer[]>("/customers"),
      ]);
      setOrders(o);
      setProducts(p);
      setCustomers(c);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const allVariants = products.flatMap((p) =>
    (p.variants ?? []).map((v) => ({
      ...v,
      label: `${p.title}${v.title ? ` — ${v.title}` : ""}${v.sku ? ` (${v.sku})` : ""}`,
      price: Number(v.price),
    })),
  );

  const total = lines.reduce((sum, line) => {
    const variant = allVariants.find((v) => v.id === line.variant_id);
    return sum + (variant ? variant.price * line.quantity : 0);
  }, 0);

  async function createOrder() {
    setBusy(true);
    setError("");
    setOk("");
    try {
      const items = lines.filter((l) => l.variant_id).map((l) => ({ variant_id: l.variant_id, quantity: l.quantity }));
      if (!customerId || items.length === 0) throw new Error("اختر عميل وواحد منتج على الأقل");
      const created = await api<{ number: string }>("/orders", {
        method: "POST",
        body: { customer_id: customerId, items, channel: "dashboard" },
      });
      setOk(`تم إنشاء الطلب ${created.number}`);
      setLines([{ variant_id: "", quantity: 1 }]);
      setCustomerId("");
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1 className="page-title">{t.orders}</h1>
        <button className="btn" onClick={() => setShowForm(!showForm)} data-testid="toggle-order-form">
          {showForm ? t.cancel : t.createOrder}
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {ok && <p className="ok-text">{ok}</p>}

      {showForm && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <div className="form-grid">
            <div>
              <label htmlFor="o-customer">{t.customer}</label>
              <select id="o-customer" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                <option value="">— اختر عميل —</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} {c.phone ? `(${c.phone})` : ""}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {lines.map((line, index) => (
            <div className="form-grid" key={index} style={{ gridTemplateColumns: "2fr 1fr auto", alignItems: "end" }}>
              <div>
                <label>المنتج {index + 1}</label>
                <select
                  value={line.variant_id}
                  onChange={(e) =>
                    setLines(lines.map((l, i) => (i === index ? { ...l, variant_id: e.target.value } : l)))
                  }
                >
                  <option value="">— اختر منتج —</option>
                  {allVariants.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label} — {v.price.toFixed(2)}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label>{t.quantity}</label>
                <input
                  type="number"
                  dir="ltr"
                  min={1}
                  value={line.quantity}
                  onChange={(e) =>
                    setLines(
                      lines.map((l, i) => (i === index ? { ...l, quantity: Math.max(1, Number(e.target.value)) } : l)),
                    )
                  }
                />
              </div>
              <div>
                {lines.length > 1 && (
                  <button
                    className="btn btn-danger"
                    onClick={() => setLines(lines.filter((_, i) => i !== index))}
                    aria-label="حذف السطر"
                  >
                    ×
                  </button>
                )}
              </div>
            </div>
          ))}

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "0.75rem" }}>
            <button className="btn btn-secondary" onClick={() => setLines([...lines, { variant_id: "", quantity: 1 }])}>
              + سطر
            </button>
            <div>
              <strong dir="ltr" style={{ marginInlineEnd: "1rem" }}>
                {total.toFixed(2)} EGP
              </strong>
              <button className="btn" onClick={createOrder} disabled={busy || !customerId || total === 0} data-testid="submit-order">
                {t.createOrder}
              </button>
            </div>
          </div>
        </div>
      )}

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
                <td dir="ltr" style={{ fontSize: 12 }}>
                  {customers.find((c) => c.id === o.customer_id)?.name ?? `${o.customer_id.slice(0, 8)}…`}
                </td>
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
