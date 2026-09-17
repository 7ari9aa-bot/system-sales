"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/t";

type Variant = { id: string; sku: string | null; title: string | null; price: string };
type Product = {
  id: string;
  title: string;
  slug: string;
  status: string;
  variants?: Variant[];
};

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [title, setTitle] = useState("");
  const [price, setPrice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setProducts(await api<Product[]>("/products"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function create() {
    if (!title.trim() || !price) return;
    setBusy(true);
    setError("");
    try {
      await api("/products", {
        method: "POST",
        body: { title, slug: `${title.trim().toLowerCase().replace(/\s+/g, "-")}-${Date.now().toString(36)}`, price: Number(price) },
      });
      setTitle("");
      setPrice("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    } finally {
      setBusy(false);
    }
  }

  const STATUS_BADGE: Record<string, string> = {
    active: "badge-success",
    draft: "badge",
    archived: "badge-danger",
  };

  return (
    <div>
      <h1 className="page-title">{t.products}</h1>
      <div className="card" style={{ marginBottom: "1rem" }}>
        <div className="form-grid">
          <div>
            <label htmlFor="p-title">{t.productTitle}</label>
            <input id="p-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <label htmlFor="p-price">{t.price}</label>
            <input
              id="p-price"
              type="number"
              dir="ltr"
              min="0"
              step="0.01"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </div>
          <div style={{ alignSelf: "end" }}>
            <button className="btn" onClick={create} disabled={busy || !title.trim() || !price} data-testid="create-product">
              {t.addProduct}
            </button>
          </div>
        </div>
        {error && <p className="error-text">{error}</p>}
      </div>

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>{t.productTitle}</th>
              <th>SKU</th>
              <th>{t.price}</th>
              <th>{t.status}</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id}>
                <td>{p.title}</td>
                <td dir="ltr">{p.variants?.[0]?.sku ?? "—"}</td>
                <td dir="ltr">{p.variants?.[0]?.price ?? "—"}</td>
                <td>
                  <span className={`badge ${STATUS_BADGE[p.status] ?? ""}`}>{p.status}</span>
                </td>
              </tr>
            ))}
            {products.length === 0 && (
              <tr>
                <td colSpan={4} className="empty">
                  لا توجد منتجات
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
