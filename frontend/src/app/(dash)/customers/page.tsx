"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/t";

type Customer = {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  lifetime_value: string;
  is_blocked: boolean;
};

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const q = search.trim() ? `?search=${encodeURIComponent(search.trim())}` : "";
      setCustomers((await api<{ items: Customer[] }>(`/customers${q}`)).items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }, [search]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <h1 className="page-title">{t.customers}</h1>
      {error && <p className="error-text">{error}</p>}
      <div style={{ marginBottom: "1rem", maxWidth: 320 }}>
        <input
          placeholder="بحث بالاسم أو الهاتف…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          data-testid="customer-search"
        />
      </div>
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>الاسم</th>
              <th>الهاتف</th>
              <th>{t.email}</th>
              <th>إجمالي الشراء</th>
            </tr>
          </thead>
          <tbody>
            {customers.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td dir="ltr">{c.phone ?? "—"}</td>
                <td dir="ltr">{c.email ?? "—"}</td>
                <td dir="ltr">{Number(c.lifetime_value).toFixed(2)}</td>
              </tr>
            ))}
            {customers.length === 0 && (
              <tr>
                <td colSpan={4} className="empty">
                  لا يوجد عملاء
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
