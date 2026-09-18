"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/t";

type Dashboard = {
  orders: { orders_count: number; revenue: number; aov: number };
  ai_orders_30d: number;
  conversations: { open: number; unread: number };
  customers: number;
  products_active: number;
  low_stock: number;
  daily_orders: { day: string; orders: number; revenue: number }[];
  revenue_by_source: { source: string; revenue: number; conversions: number }[];
};

function Stat({
  label,
  value,
  hint,
  testid,
}: {
  label: string;
  value: string | number;
  hint?: string;
  testid?: string;
}) {
  return (
    <div className="card stat" data-testid={testid}>
      <div className="value" dir="ltr">
        {typeof value === "number" ? value.toLocaleString("en-US") : value}
      </div>
      <div className="label">{label}</div>
      {hint && <div className="muted" style={{ fontSize: 12 }}>{hint}</div>}
    </div>
  );
}

function BarChart({ data }: { data: { day: string; revenue: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.revenue));
  if (data.length === 0) return <div className="empty">لا توجد بيانات بعد</div>;
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 140, paddingTop: 8 }}>
      {data.map((d) => (
        <div key={d.day} style={{ flex: 1, textAlign: "center" }} title={`${d.day}: ${d.revenue}`}>
          <div
            style={{
              height: `${Math.max(4, (d.revenue / max) * 110)}px`,
              background: "var(--primary)",
              borderRadius: 4,
              opacity: 0.85,
            }}
          />
          <div className="muted" style={{ fontSize: 10, marginTop: 4 }}>
            {new Date(d.day).getDate()}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api<Dashboard>("/analytics/dashboard"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 20000);
    return () => clearInterval(timer);
  }, [load]);

  if (error) return <p className="error-text">{error}</p>;
  if (!data) return <div className="empty">{t.loading}</div>;

  const sources = [...data.revenue_by_source].sort((a, b) => b.revenue - a.revenue).slice(0, 5);
  const maxSource = Math.max(1, ...sources.map((s) => s.revenue));

  return (
    <div>
      <h1 className="page-title">{t.dashboard}</h1>
      <div className="stats-grid">
        <Stat
          label="إيرادات 30 يوم"
          value={`${Number(data.orders.revenue).toFixed(0)} ${"ج.م"}`}
          testid="stat-revenue"
        />
        <Stat label="الطلبات (30 يوم)" value={data.orders.orders_count} testid="stat-orders" />
        <Stat
          label="متوسط قيمة الطلب"
          value={Number(data.orders.aov).toFixed(0)}
          testid="stat-aov"
        />
        <Stat
          label="محادثات مفتوحة"
          value={data.conversations.open}
          hint={`${data.conversations.unread} غير مقروءة`}
          testid="stat-conversations"
        />
        <Stat label="العملاء" value={data.customers} testid="stat-customers" />
        <Stat
          label="منتجات مفعّلة"
          value={data.products_active}
          hint={data.low_stock > 0 ? `${data.low_stock} منتج شبه نافد` : undefined}
          testid="stat-products"
        />
      </div>

      {data.low_stock > 0 && (
        <div className="card" style={{ marginBottom: "1rem", borderInlineStart: "3px solid var(--warning)" }}>
          ⚠️ عندك {data.low_stock} صنف مخزونه على وشك النفاد — راجع صفحة {t.inventory}.
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>الإيرادات اليومية (14 يوم)</h3>
          <BarChart data={data.daily_orders} />
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>الإيرادات حسب المصدر</h3>
          {sources.length === 0 && <div className="empty">لا توجد تحويلات مرتبطة بمصادر</div>}
          {sources.map((s) => (
            <div key={s.source} style={{ marginBottom: "0.7rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <strong>{s.source}</strong>
                <span dir="ltr">
                  {Number(s.revenue).toFixed(0)} ({s.conversions})
                </span>
              </div>
              <div style={{ background: "#eef1f8", borderRadius: 4, height: 8 }}>
                <div
                  style={{
                    width: `${(s.revenue / maxSource) * 100}%`,
                    background: "var(--success)",
                    height: 8,
                    borderRadius: 4,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
