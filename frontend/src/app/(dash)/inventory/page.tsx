"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/t";

type Balance = {
  variant_id: string;
  warehouse_id: string;
  on_hand: number;
  reserved: number;
};

type Movement = {
  id: string;
  variant_id: string;
  direction: string;
  quantity: number;
  reason: string;
  balance_after: number;
  created_at: string;
};

export default function InventoryPage() {
  const [balances, setBalances] = useState<Balance[]>([]);
  const [movements, setMovements] = useState<Movement[]>([]);
  const [variantId, setVariantId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [direction, setDirection] = useState("in");
  const [quantity, setQuantity] = useState("1");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  const load = useCallback(async () => {
    try {
      const [b, m] = await Promise.all([
        api<Balance[]>("/inventory/balances"),
        api<Movement[]>("/inventory/movements"),
      ]);
      setBalances(b);
      setMovements(m);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function record() {
    setError("");
    setOk("");
    try {
      await api("/inventory/movements", {
        method: "POST",
        body: {
          variant_id: variantId,
          warehouse_id: warehouseId,
          direction,
          quantity: Number(quantity),
          reason: direction === "in" ? "purchase" : direction === "out" ? "sale" : "adjustment",
        },
      });
      setOk("تم تسجيل الحركة");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }

  return (
    <div>
      <h1 className="page-title">{t.inventory}</h1>

      <div className="card" style={{ marginBottom: "1rem" }}>
        <div className="form-grid">
          <div>
            <label htmlFor="iv-variant">Variant ID</label>
            <input id="iv-variant" dir="ltr" value={variantId} onChange={(e) => setVariantId(e.target.value)} />
          </div>
          <div>
            <label htmlFor="iv-wh">{t.warehouse}</label>
            <input id="iv-wh" dir="ltr" value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} />
          </div>
          <div>
            <label htmlFor="iv-dir">نوع الحركة</label>
            <select id="iv-dir" value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="in">{t.in}</option>
              <option value="out">{t.out}</option>
              <option value="adjust">{t.adjust}</option>
            </select>
          </div>
          <div>
            <label htmlFor="iv-qty">{t.quantity}</label>
            <input
              id="iv-qty"
              type="number"
              dir="ltr"
              min="1"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </div>
          <div style={{ alignSelf: "end" }}>
            <button className="btn" onClick={record} disabled={!variantId || !warehouseId} data-testid="record-movement">
              {t.recordMovement}
            </button>
          </div>
        </div>
        {error && <p className="error-text">{error}</p>}
        {ok && <p className="ok-text">{ok}</p>}
      </div>

      <div className="card" style={{ marginBottom: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>الأرصدة</h3>
        <table className="table">
          <thead>
            <tr>
              <th>Variant</th>
              <th>{t.warehouse}</th>
              <th>{t.onHand}</th>
              <th>{t.reserved}</th>
            </tr>
          </thead>
          <tbody>
            {balances.map((b) => (
              <tr key={`${b.variant_id}-${b.warehouse_id}`}>
                <td dir="ltr" style={{ fontSize: 12 }}>{b.variant_id.slice(0, 8)}…</td>
                <td dir="ltr" style={{ fontSize: 12 }}>{b.warehouse_id.slice(0, 8)}…</td>
                <td dir="ltr">{b.on_hand}</td>
                <td dir="ltr">{b.reserved}</td>
              </tr>
            ))}
            {balances.length === 0 && (
              <tr>
                <td colSpan={4} className="empty">لا توجد أرصدة</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>سجل الحركات</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t.date}</th>
              <th>Variant</th>
              <th>النوع</th>
              <th>{t.quantity}</th>
              <th>الرصيد بعد</th>
              <th>السبب</th>
            </tr>
          </thead>
          <tbody>
            {movements.slice(0, 20).map((m) => (
              <tr key={m.id}>
                <td dir="ltr" style={{ fontSize: 12 }}>{new Date(m.created_at).toLocaleString("ar-EG-u-nu-latn")}</td>
                <td dir="ltr" style={{ fontSize: 12 }}>{m.variant_id.slice(0, 8)}…</td>
                <td>
                  <span className={`badge ${m.direction === "in" ? "badge-success" : m.direction === "out" ? "badge-danger" : ""}`}>
                    {m.direction === "in" ? t.in : m.direction === "out" ? t.out : t.adjust}
                  </span>
                </td>
                <td dir="ltr">{m.quantity}</td>
                <td dir="ltr">{m.balance_after}</td>
                <td>{m.reason}</td>
              </tr>
            ))}
            {movements.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">لا توجد حركات</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
