import { useCallback, useEffect, useMemo, useState } from "react";
import { apiCached, peekCache } from "@/lib/api";
import { setRegionalConfig, useRegional } from "@/lib/regional";

const DAYS = { "7d": 7, "30d": 30, "90d": 90 };

function zonedParts(date, timezone) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  return Object.fromEntries(parts.map(({ type, value }) => [type, value]));
}

function zonedMidnightToUtc({ year, month, day }, timezone) {
  const target = { year: Number(year), month: Number(month), day: Number(day), hour: 0, minute: 0, second: 0 };
  const desiredUtc = Date.UTC(target.year, target.month - 1, target.day);
  let guess = desiredUtc;
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const parts = Object.fromEntries(formatter.formatToParts(new Date(guess)).map(({ type, value }) => [type, value]));
    const observedUtc = Date.UTC(
      Number(parts.year), Number(parts.month) - 1, Number(parts.day),
      Number(parts.hour), Number(parts.minute), Number(parts.second),
    );
    const delta = desiredUtc - observedUtc;
    if (delta === 0) break;
    guess += delta;
  }
  return new Date(guess);
}

function overviewPath(range, timezone) {
  const params = new URLSearchParams();
  if (range === "today" || range === "yesterday") {
    const now = new Date();
    const todayParts = zonedParts(now, timezone);
    const todayStart = zonedMidnightToUtc(todayParts, timezone);
    if (range === "today") {
      params.set("since", todayStart.toISOString());
      params.set("until", now.toISOString());
    } else {
      const previousDay = new Date(Date.UTC(Number(todayParts.year), Number(todayParts.month) - 1, Number(todayParts.day) - 1));
      const previousParts = {
        year: previousDay.getUTCFullYear(),
        month: previousDay.getUTCMonth() + 1,
        day: previousDay.getUTCDate(),
      };
      params.set("since", zonedMidnightToUtc(previousParts, timezone).toISOString());
      params.set("until", todayStart.toISOString());
    }
    params.set("timezone", timezone);
  } else {
    params.set("days", String(DAYS[range] || DAYS["30d"]));
    params.set("timezone", timezone);
  }
  return `/analytics/overview?${params.toString()}`;
}

/** نافذة سابقة بنفس الطول، محسوبة من `since`/`until` اللي رجّعهم السيرفر نفسه —
 *  فالمقارنة بتبقى بين نافذتين متطابقتي الطول ومن نفس المرجع الزمني، مش تقدير
 *  من الساعة بتاعة المتصفح. */
function previousWindow(overview) {
  const from = Date.parse(overview?.since ?? "");
  const to = Date.parse(overview?.until ?? "");
  if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) return null;
  const span = to - from;
  const params = new URLSearchParams();
  params.set("since", new Date(from - span).toISOString());
  params.set("until", new Date(from).toISOString());
  if (overview.timezone) params.set("timezone", overview.timezone);
  return `/analytics/overview?${params.toString()}`;
}

function percentDelta(current, previous) {
  const now = Number(current);
  const before = Number(previous);
  if (!Number.isFinite(now) || !Number.isFinite(before) || before === 0) return null;
  return ((now - before) / Math.abs(before)) * 100;
}

/** أرقام المبيعات الحقيقية لنطاق الداشبورد — من read models السيرفر:
 *  GET /analytics/dashboard للبيانات المساندة وGET /analytics/overview
 *  للنطاق المحدد، مع حدود اليوم المحلي في إعداد المنطقة الزمنية. */
export default function useSalesStats(range) {
  const [dash, setDash] = useState(() => peekCache("/analytics/dashboard") || null);
  const [overviewState, setOverviewState] = useState({ path: null, data: null });
  const [previous, setPrevious] = useState({ path: null, data: null });
  const [overviewFailure, setOverviewFailure] = useState({ path: null, error: "" });
  const [dashboardError, setDashboardError] = useState("");
  const [dashboardAttempt, setDashboardAttempt] = useState(0);
  const [overviewAttempt, setOverviewAttempt] = useState(0);
  const { country } = useRegional();
  const timezone = dash?.orders?.timezone || country.timezone;
  const path = useMemo(() => overviewPath(range, timezone), [range, timezone]);
  const overview = overviewState.path === path ? overviewState.data : null;
  const overviewError = overviewFailure.path === path ? overviewFailure.error : "";
  const currency = overview?.currency || dash?.orders?.currency;

  const retryDashboard = useCallback(() => setDashboardAttempt((attempt) => attempt + 1), []);
  const retryOverview = useCallback(() => setOverviewAttempt((attempt) => attempt + 1), []);

  useEffect(() => {
    if (currency) setRegionalConfig({ currency });
  }, [currency]);

  useEffect(() => {
    let alive = true;
    const cached = peekCache("/analytics/dashboard");
    if (cached) setDash(cached);
    setDashboardError("");
    apiCached("/analytics/dashboard")
      .then((d) => {
        if (!alive) return;
        setDash(d);
        setDashboardError("");
      })
      .catch((error) => {
        if (!alive) return;
        setDashboardError(error?.message || "Could not load dashboard data");
      });
    return () => {
      alive = false;
    };
  }, [dashboardAttempt]);

  useEffect(() => {
    let alive = true;
    const cached = peekCache(path);
    setOverviewState({ path, data: cached || null });
    setOverviewFailure({ path, error: "" });
    apiCached(path)
      .then((d) => alive && setOverviewState({ path, data: d }))
      .catch((error) => {
        if (!alive) return;
        setOverviewState({ path, data: null });
        setOverviewFailure({ path, error: error?.message || "Could not load sales overview" });
      });
    return () => {
      alive = false;
    };
  }, [path, overviewAttempt]);

  const prevPath = useMemo(() => (overview ? previousWindow(overview) : null), [overview]);

  useEffect(() => {
    if (!prevPath) {
      setPrevious({ path: null, data: null });
      return undefined;
    }
    let alive = true;
    const cached = peekCache(prevPath);
    if (cached) setPrevious({ path: prevPath, data: cached });
    apiCached(prevPath)
      .then((d) => alive && setPrevious({ path: prevPath, data: d }))
      .catch(() => alive && setPrevious({ path: prevPath, data: null }));
    return () => {
      alive = false;
    };
  }, [prevPath]);

  return useMemo(() => {
    if (!dash) {
      return dashboardError
        ? { dashboardError, retryDashboard, overviewError, retryOverview }
        : null;
    }
    const customers = dash.customers ?? null;
    const before = prevPath && previous.path === prevPath ? previous.data : null;
    const trend = (overview?.daily_series ?? []).map((r) => ({
      label: r.day,
      revenue: Number(r.net_revenue ?? 0),
      orders: r.orders_count ?? 0,
    }));
    return {
      netSales: overview == null ? null : Number(overview.net_revenue ?? 0),
      netSalesDelta: before ? percentDelta(overview?.net_revenue, before.net_revenue) : null,
      orders: overview == null ? null : overview.orders_count ?? 0,
      ordersDelta: before ? percentDelta(overview?.orders_count, before.orders_count) : null,
      customers,
      aiOrders: dash.ai_orders_30d ?? null,
      activeProducts: dash.products_active ?? null,
      unread: dash.conversations?.unread ?? null,
      openConversations: dash.conversations?.open ?? null,
      lowStock: dash.low_stock_count ?? null,
      outOfStock: dash.out_of_stock_count ?? null,
      sources: dash.revenue_by_source ?? null,
      trend: trend.length ? trend : [],
      overviewLoading: overview == null && !overviewError,
      overviewError,
      dashboardError,
      retryDashboard,
      retryOverview,
    };
  }, [dash, overview, previous, prevPath, dashboardError, overviewError, retryDashboard, retryOverview]);
}
