/**
 * Preview-only mock API — للمعاينة المحلية فقط، مش جزء من التطبيق.
 *
 * بيحاكي شكل الـFastAPI backend (نفس الـwire shapes) ببيانات تجريبية
 * عشان تقدر تتصفح الداشبورد والصفحة الرئيسية من غير قاعدة بيانات.
 * التشغيل:  node scripts/preview-mock-api.mjs   (بيسمع على :8000)
 * الفلوس نصوص زي ما الـbackend بيبعتها (ADR-001) — مفيش floats.
 */

import http from "node:http";

const PORT = 8100;

/* ------------------------------------------------------------- helpers */

const money = (n) => n.toFixed(2);
let lastEmail = "owner@fihrist.app";

function iso(d) {
  return d.toISOString();
}

function dayStr(d) {
  return d.toISOString().slice(0, 10);
}

function seriesFor(days) {
  const out = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    const wave = Math.sin(i / 3) * 900 + (i % 7 === 5 ? 1400 : 0);
    const gross = Math.max(300, Math.round(3200 + wave + i * 40));
    const refunded = i % 9 === 0 ? Math.round(gross * 0.15) : 0;
    out.push({
      day: dayStr(d),
      orders: Math.max(2, Math.round(gross / 290)),
      gross_revenue: money(gross),
      refunded_amount: money(refunded),
      net_revenue: money(gross - refunded),
      refund_excess: "0.00",
    });
  }
  return out;
}

const DASHBOARD = {
  orders: {
    orders_count: 426,
    gross_revenue: money(131820),
    refunded_amount: money(7000),
    net_revenue: money(124820),
    refund_excess: "0.00",
    gross_aov: money(309.44),
    net_aov: money(293.0),
    currency: "EGP",
    timezone: "Africa/Cairo",
  },
  ai_orders_30d: 64,
  conversations: { open: 14, unread: 8 },
  customers: 3842,
  products_active: 46,
  low_stock_count: 12,
  out_of_stock_count: 5,
  low_stock_threshold: 10,
  daily_orders: seriesFor(30),
  revenue_by_source: [
    { source: "whatsapp", revenue: money(52400), conversions: 186 },
    { source: "instagram", revenue: money(31200), conversions: 124 },
    { source: "direct", revenue: money(22600), conversions: 91 },
    { source: "facebook", revenue: money(11840), conversions: 47 },
  ],
};

function overviewFor(days) {
  const rows = seriesFor(days);
  const sum = (key) => rows.reduce((acc, r) => acc + Number(r[key]), 0);
  const gross = sum("gross_revenue");
  const refunded = sum("refunded_amount");
  const count = rows.reduce((acc, r) => acc + r.orders, 0);
  return {
    since: rows[0]?.day ?? dayStr(new Date()),
    until: dayStr(new Date()),
    currency: "EGP",
    timezone: "Africa/Cairo",
    orders_count: count,
    gross_revenue: money(gross),
    refunded_amount: money(refunded),
    net_revenue: money(gross - refunded),
    refund_excess: "0.00",
    gross_aov: money(count ? gross / count : 0),
    net_aov: money(count ? (gross - refunded) / count : 0),
    daily_series: rows,
    stock: { low_stock_threshold: 10, low_stock_count: 12, out_of_stock_count: 5, healthy_count: 46 },
  };
}

const PRODUCTS = [
  { id: "p1", title: "قميص كتان — رملي", slug: "linen-shirt-sand", status: "active" },
  { id: "p2", title: "طقم سيراميك للتحضير", slug: "ceramic-pourover", status: "active" },
  { id: "p3", title: "بطن صوف — ستون", slug: "wool-throw-stone", status: "active" },
  { id: "p4", title: "مصباح نحاسي للمكتب", slug: "brass-desk-lamp", status: "active" },
  { id: "p5", title: "عبادة قطن — كلاي", slug: "cotton-robe-clay", status: "draft" },
];

const CUSTOMERS = {
  items: [
    { id: "c1", name: "ليلى حسن", phone: "+201000000001", email: null, lifetime_value: "1840.00", is_blocked: false },
    { id: "c2", name: "عمر خالد", phone: "+201000000002", email: null, lifetime_value: "620.00", is_blocked: false },
    { id: "c3", name: "نورة علي", phone: "+201000000003", email: null, lifetime_value: "3980.00", is_blocked: false },
    { id: "c4", name: "سامي طارق", phone: "+201000000004", email: "sami@example.com", lifetime_value: "140.00", is_blocked: false },
  ],
  next_cursor: null,
};

const ORDERS = {
  items: [
    { id: "o1", number: "2048", customer_id: "c3", status: "fulfilled", grand_total: "580.00", currency: "EGP", placed_at: iso(new Date()), created_at: iso(new Date()) },
    { id: "o2", number: "2047", customer_id: "c1", status: "processing", grand_total: "240.00", currency: "EGP", placed_at: iso(new Date()), created_at: iso(new Date()) },
    { id: "o3", number: "2046", customer_id: "c2", status: "processing", grand_total: "920.00", currency: "EGP", placed_at: iso(new Date()), created_at: iso(new Date()) },
    { id: "o4", number: "2045", customer_id: "c4", status: "awaiting_shipment", grand_total: "1640.00", currency: "EGP", placed_at: iso(new Date()), created_at: iso(new Date()) },
  ],
  next_cursor: null,
};

const APPROVALS = {
  items: [
    {
      id: "ap1", status: "PENDING", action: "issue_refund", risk_level: "HIGH",
      entity_type: "order", entity_id: "o2", conversation_id: "cnv1", run_id: "run1",
      payload: { reason: "طلب عميل — منتج تالف" }, requested_by: "agent-1",
      expires_at: iso(new Date(Date.now() + 86400000)), decided_at: null,
    },
    {
      id: "ap2", status: "PENDING", action: "place_order", risk_level: "HIGH",
      entity_type: "conversation", entity_id: "cnv2", conversation_id: "cnv2", run_id: "run2",
      payload: { total: "310.00" }, requested_by: "agent-1",
      expires_at: iso(new Date(Date.now() + 86400000)), decided_at: null,
    },
  ],
  truncated: false,
};

const NOTIFICATIONS = [
  { id: "n1", kind: "approval", title: "موافقة جديدة", body: "إرجاع مبلغ على الطلب 2047 محتاج موافقتك.", action_url: "/approvals", payload: {}, read_at: null, created_at: iso(new Date()) },
  { id: "n2", kind: "inventory", title: "مخزون منخفض", body: "12 منتج أوشكوا على النفاد.", action_url: "/inventory", payload: {}, read_at: null, created_at: iso(new Date()) },
  { id: "n3", kind: "order", title: "طلب جديد", body: "الطلب 2048 اتصرف بنجاح.", action_url: "/orders", payload: {}, read_at: iso(new Date()), created_at: iso(new Date()) },
];

const CONVERSATIONS = {
  items: [
    { id: "cnv1", customer_id: "c1", channel: "whatsapp", status: "waiting_human", last_message_preview: "هل العرض يشمل التوصيل؟", unread_count: 2, assignee_user_id: null, sla_status: "ok", sla_deadline_at: iso(new Date(Date.now() + 3600000)) },
    { id: "cnv2", customer_id: "c2", channel: "instagram", status: "waiting_ai", last_message_preview: "ممكن خصم لو طلبت 3؟", unread_count: 1, assignee_user_id: null, sla_status: "at_risk", sla_deadline_at: iso(new Date(Date.now() + 600000)) },
    { id: "cnv3", customer_id: "c3", channel: "whatsapp", status: "resolved", last_message_preview: "شكرًا! الطلب وصل النهاردة.", unread_count: 0, assignee_user_id: "user-1", sla_status: "ok", sla_deadline_at: null },
  ],
  next_cursor: null,
};

/* ------------------------------------------------------------- server */

function json(res, body, status = 200) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, If-Match, Idempotency-Key",
    "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS",
    "Access-Control-Expose-Headers": "ETag, Idempotency-Replayed",
  });
  res.end(data);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const path = url.pathname.replace(/^\/api\/v1/, "").replace(/\/$/, "");
  const q = url.searchParams;

  if (req.method === "OPTIONS") return json(res, {});

  // ---------------------------------------------------------- auth
  if (path === "/auth/login" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      try { lastEmail = JSON.parse(body)?.email || lastEmail; } catch {}
      json(res, { access_token: "preview-access-token", refresh_token: "preview-refresh-token", token_type: "bearer" });
    });
    return;
  }
  if (path === "/auth/logout") return json(res, {});
  if (path === "/auth/me") {
    return json(res, { id: "user-1", email: lastEmail, tenants: [{ id: "tenant-1" }] });
  }

  // ---------------------------------------------------------- analytics
  if (path === "/analytics/dashboard") return json(res, DASHBOARD);
  if (path === "/analytics/overview") return json(res, overviewFor(Number(q.get("days") ?? 30)));
  if (path === "/analytics/summary") {
    return json(res, {
      orders_summary: DASHBOARD.orders,
      revenue_by_source: DASHBOARD.revenue_by_source,
      revenue_by_campaign: [
        { campaign_id: "m1", campaign_name: "إطلاق الخريف", revenue: money(9200), conversions: 48 },
        { campaign_id: "m2", campaign_name: "تذكير العملاء المميزين", revenue: money(6400), conversions: 52 },
      ],
      campaign_budget_roas: [],
    });
  }

  // ---------------------------------------------------------- AI
  if (path === "/ai/usage/summary") {
    const now = new Date();
    const summary = Array.from({ length: 14 }, (_, i) => {
      const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
      return {
        date: dayStr(d),
        tokens_in: 90000 + i * 1500,
        tokens_out: 42000 + i * 800,
        cost: money(1.8 + (i % 5) * 0.3),
      };
    });
    return json(res, {
      summary,
      totals: { cost: money(42.18), tokens_in: 6820000, tokens_out: 2910000 },
    });
  }
  if (path === "/ai/approvals") return json(res, APPROVALS);
  if (path === "/ai/agents") {
    return json(res, [
      { id: "agent-1", name: "مساعد المبيعات", model: "qwen3.8-omni-flash", is_active: true },
      { id: "agent-2", name: "مساعد الدعم", model: "qwen3.8-omni-flash", is_active: true },
    ]);
  }
  if (path === "/ai/knowledge") return json(res, { items: [], next_cursor: null });

  // ---------------------------------------------------------- marketing
  if (path === "/marketing/campaigns") {
    return json(res, {
      items: [
        { id: "m1", name: "إطلاق الخريف", provider: "whatsapp", status: "active", budget: "5000.00" },
        { id: "m2", name: "تذكير العملاء المميزين", provider: "instagram", status: "active", budget: "3200.00" },
        { id: "m3", name: "تنضيف المخزون الصيفي", provider: "instagram", status: "ended", budget: "2800.00" },
      ],
      next_cursor: null,
    });
  }

  // ---------------------------------------------------------- notifications
  if (path === "/notifications/unread-count") return json(res, { count: 2 });
  if (path === "/notifications/summary") return json(res, { total: 3, unread: 2, by_kind: [] });
  if (path === "/notifications") return json(res, NOTIFICATIONS);

  // ---------------------------------------------------------- platform
  if (path === "/platform/health") {
    return json(res, { status: "healthy", subsystems: [] });
  }

  // ---------------------------------------------------------- search
  if (path === "/search") {
    const term = (q.get("q") ?? "").trim().toLowerCase();
    const hits = [];
    for (const c of CUSTOMERS.items) {
      if (term && c.name.includes(term)) hits.push({ entity_type: "customer", entity_id: c.id, title: c.name, snippet: `LTV ${c.lifetime_value}` });
    }
    for (const o of ORDERS.items) {
      if (term && (o.number.includes(term) || o.id.includes(term))) hits.push({ entity_type: "order", entity_id: o.id, title: `الطلب ${o.number}`, snippet: o.grand_total });
    }
    for (const p of PRODUCTS) {
      if (term && p.title.includes(term)) hits.push({ entity_type: "product", entity_id: p.id, title: p.title, snippet: p.slug });
    }
    return json(res, hits.slice(0, 8));
  }

  // ---------------------------------------------------------- entities
  if (path === "/products") return json(res, PRODUCTS);
  if (path === "/customers") return json(res, CUSTOMERS);
  if (path === "/orders") return json(res, ORDERS);
  if (path === "/conversations") return json(res, CONVERSATIONS);
  if (path === "/inventory/balances") return json(res, []);
  if (path === "/inventory/movements") return json(res, []);
  if (path === "/tasks") return json(res, []);
  if (path === "/invitations") return json(res, []);
  if (path === "/integrations") {
    return json(res, [
      { id: "in1", provider: "whatsapp", kind: "channel", status: "connected" },
      { id: "in2", provider: "instagram", kind: "channel", status: "connected" },
      { id: "in3", provider: "telegram", kind: "channel", status: "disconnected" },
    ]);
  }

  // ---------------------------------------------------------- realtime SSE
  if (path === "/realtime/events") {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "Access-Control-Allow-Origin": "*",
    });
    res.write("retry: 5000\n\n");
    const beat = setInterval(() => res.write(": ping\n\n"), 20000);
    req.on("close", () => clearInterval(beat));
    return;
  }

  // Fallback: كائن فاضي عشان أي نداء غير مغطى يرجع 200 آمن
  json(res, { items: [], next_cursor: null });
});

server.listen(PORT, () => {
  console.log(`[preview-mock-api] listening on http://localhost:${PORT} (preview only)`);
});
