import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";

const DAYS = { today: 1, yesterday: 2, "7d": 7, "30d": 30, "90d": 90, custom: 30 };

function startOfDay(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

const fmts = {};
function fmtFor(lang) {
  if (!fmts[lang]) {
    fmts[lang] = new Intl.DateTimeFormat(lang === "ar" ? "ar-EG" : "en-US", {
      month: "short",
      day: "numeric",
    });
  }
  return fmts[lang];
}

/** أرقام المبيعات الحقيقية لنطاق الداشبورد — من read models السيرفر:
 *  GET /analytics/dashboard للبطاقات (صافي بعد المرتجعات) و
 *  GET /analytics/overview?days=N للسلسلة اليومية بخانة اليوم
 *  التجاري للمستأجر. بيرجع null أثناء التحميل. */
export default function useSalesStats(range) {
  const [dash, setDash] = useState(null);
  const [overview, setOverview] = useState(null);
  const lang = (typeof window !== "undefined" && window.localStorage.getItem("fihrist.locale")) || "ar";
  const days = DAYS[range] || 30;

  useEffect(() => {
    let alive = true;
    api("/analytics/dashboard")
      .then((d) => alive && setDash(d))
      .catch(() => alive && setDash(null));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    setOverview(null);
    api(`/analytics/overview?days=${days}`)
      .then((d) => alive && setOverview(d))
      .catch(() => alive && setOverview(null));
    return () => {
      alive = false;
    };
  }, [days]);

  return useMemo(() => {
    if (!dash) return null;
    const orders = dash.orders ?? {};
    const netSales = Number(orders.net_revenue ?? 0);
    const ordersCount = orders.orders_count ?? 0;
    const customers = dash.customers ?? 0;
    const fmt = fmtFor(lang);
    const trend = (overview?.daily_series ?? []).map((r) => ({
      label: r.day,
      revenue: Number(r.net_revenue ?? 0),
      orders: r.orders_count ?? 0,
    }));
    const shown = overview?.daily_series?.length
      ? overview
      : { orders_count: ordersCount, net_revenue: orders.net_revenue };
    return {
      netSales,
      orders: shown?.orders_count ?? ordersCount,
      customers,
      aiOrders: dash.ai_orders_30d ?? 0,
      activeProducts: dash.products_active ?? 0,
      unread: dash.conversations?.unread ?? 0,
      openConversations: dash.conversations?.open ?? 0,
      lowStock: dash.low_stock_count ?? 0,
      outOfStock: dash.out_of_stock_count ?? 0,
      sources: dash.revenue_by_source ?? [],
      trend: trend.length ? trend : [],
    };
  }, [dash, overview, lang]);
}
