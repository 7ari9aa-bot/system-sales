// Central mock business data for Sales OS dashboard.
// Designed around business-level read models (not raw database rows).

export const DATE_RANGES = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "7d", label: "Last 7 days" },
  { id: "30d", label: "Last 30 days" },
  { id: "90d", label: "Last 90 days" },
];

export const LOCATIONS = [
  { id: "all", label: "All locations" },
  { id: "riyadh", label: "Riyadh flagship" },
  { id: "jeddah", label: "Jeddah branch" },
  { id: "online", label: "Online store" },
];

// Per-range KPI values + deltas. In a real product these come from a
// DashboardSummary read model scoped to the selected period.
export const SUMMARY_BY_RANGE = {
  today: {
    netSales: { value: 4280, delta: 6.2, orders: 14 },
    orders: { value: 14, delta: 4.3 },
    customers: { value: 38, delta: 2.1 },
    conversion: { value: 4.2, delta: 0.3 },
    aiConversations: { value: 142, delta: 9.4 },
    aiSpend: { value: 3.18, delta: -2.1 },
  },
  yesterday: {
    netSales: { value: 3980, delta: 1.8, orders: 13 },
    orders: { value: 13, delta: -1.2 },
    customers: { value: 31, delta: -3.0 },
    conversion: { value: 3.9, delta: -0.2 },
    aiConversations: { value: 128, delta: 5.1 },
    aiSpend: { value: 2.94, delta: 1.2 },
  },
  "7d": {
    netSales: { value: 31420, delta: 12.6, orders: 108 },
    orders: { value: 108, delta: 8.4 },
    customers: { value: 920, delta: 6.9 },
    conversion: { value: 4.4, delta: 0.4 },
    aiConversations: { value: 642, delta: 16.8 },
    aiSpend: { value: 11.4, delta: 4.2 },
  },
  "30d": {
    netSales: { value: 124820, delta: 18.4, orders: 426 },
    orders: { value: 426, delta: 11.2 },
    customers: { value: 3842, delta: 8.7 },
    conversion: { value: 4.8, delta: 0.6 },
    aiConversations: { value: 1842, delta: 22.1 },
    aiSpend: { value: 42.18, delta: 7.8 },
  },
  "90d": {
    netSales: { value: 386240, delta: 24.9, orders: 1284 },
    orders: { value: 1284, delta: 19.4 },
    customers: { value: 11240, delta: 14.2 },
    conversion: { value: 5.1, delta: 0.9 },
    aiConversations: { value: 5480, delta: 31.6 },
    aiSpend: { value: 118.6, delta: 12.4 },
  },
};

export const DEFAULT_RANGE = "30d";

// Sales trend series (revenue + orders) — used by the Home chart.
export const SALES_TREND = {
  "7d": Array.from({ length: 7 }, (_, i) => ({
    label: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][i],
    revenue: [3200, 4100, 3800, 5200, 6100, 5400, 3620][i],
    orders: [11, 14, 13, 18, 21, 19, 12][i],
  })),
  "30d": Array.from({ length: 30 }, (_, i) => {
    const base = 3200 + Math.sin(i / 3) * 900 + i * 90;
    return {
      label: `${i + 1}`,
      revenue: Math.round(base + (i % 7 === 0 ? 1400 : 0)),
      orders: Math.round(base / 290),
    };
  }),
  "90d": Array.from({ length: 12 }, (_, i) => ({
    label: `W${i + 1}`,
    revenue: Math.round(9000 + Math.sin(i / 2) * 2200 + i * 420),
    orders: Math.round((9000 + Math.sin(i / 2) * 2200 + i * 420) / 290),
  })),
  today: Array.from({ length: 8 }, (_, i) => ({
    label: `${(i + 8) % 24}:00`,
    revenue: Math.round(180 + Math.sin(i) * 120 + i * 40),
    orders: Math.round((180 + Math.sin(i) * 120 + i * 40) / 300),
  })),
  yesterday: Array.from({ length: 8 }, (_, i) => ({
    label: `${(i + 8) % 24}:00`,
    revenue: Math.round(160 + Math.cos(i) * 110 + i * 38),
    orders: Math.round((160 + Math.cos(i) * 110 + i * 38) / 300),
  })),
};

export const TOP_PRODUCTS = [
  { name: "Linen Shirt — Sand", revenue: 28400, units: 96, trend: 14 },
  { name: "Ceramic Pour-Over Set", revenue: 19820, units: 64, trend: 9 },
  { name: "Wool Throw — Stone", revenue: 14210, units: 52, trend: -3 },
  { name: "Brass Desk Lamp", revenue: 11860, units: 28, trend: 22 },
];

export const ATTENTION_ITEMS = [
  { id: "ap1", type: "approval", tone: "warning", titleKey: "home.attention.approvals.title", titleParams: { n: 3 }, detailKey: "home.attention.approvals.detail", actionKey: "home.attention.approvals.action", to: "/ai" },
  { id: "ap2", type: "inbox", tone: "primary", titleKey: "home.attention.inbox.title", titleParams: { n: 8 }, detailKey: "home.attention.inbox.detail", actionKey: "home.attention.inbox.action", to: "/inbox" },
  { id: "ap3", type: "inventory", tone: "destructive", titleKey: "home.attention.outOfStock.title", titleParams: { n: 5 }, detailKey: "home.attention.outOfStock.detail", actionKey: "home.attention.outOfStock.action", to: "/inventory" },
  { id: "ap4", type: "inventory", tone: "warning", titleKey: "home.attention.lowStock.title", titleParams: { n: 12 }, detailKey: "home.attention.lowStock.detail", actionKey: "home.attention.lowStock.action", to: "/inventory" },
  { id: "ap5", type: "orders", tone: "primary", titleKey: "home.attention.followup.title", titleParams: { n: 2 }, detailKey: "home.attention.followup.detail", detailParams: { n: 2 }, actionKey: "home.attention.followup.action", to: "/orders" },
  { id: "ap6", type: "channel", tone: "warning", titleKey: "home.attention.channel.title", detailKey: "home.attention.channel.detail", actionKey: "home.attention.channel.action", to: "/settings" },
];

export const AI_SUMMARY = {
  conversationsHandled: 1842,
  automationRate: 87,
  handovers: 126,
  leadsQualified: 74,
  actionsCompleted: 214,
  followUps: 38,
  ordersAssisted: 21,
  approvalsWaiting: 3,
  spendThisMonth: 42.18,
  deltaConversations: 22.1,
};

export const BUSINESS_INSIGHTS = [
  {
    id: "i1",
    tone: "success",
    titleKey: "home.insight.sales.title",
    titleParams: { pct: 24 },
    bodyKey: "home.insight.sales.body",
    bodyParams: { name: "Linen Shirt — Sand" },
    actionKey: "home.insight.sales.action",
    to: "/analytics",
  },
  {
    id: "i2",
    tone: "warning",
    titleKey: "home.insight.lowStock.title",
    titleParams: { n: 5 },
    bodyKey: "home.insight.lowStock.body",
    actionKey: "home.insight.lowStock.action",
    to: "/inventory",
  },
  {
    id: "i3",
    tone: "primary",
    titleKey: "home.insight.ai.title",
    titleParams: { pct: 31 },
    bodyKey: "home.insight.ai.body",
    actionKey: "home.insight.ai.action",
    to: "/ai",
  },
];

export const INVENTORY_SNAPSHOT = {
  inStock: 1248,
  lowStock: 12,
  outOfStock: 5,
  mayNeedRestock: 5,
};

export const MARKETING_SNAPSHOT = {
  activeCampaigns: 3,
  attributedRevenue: 18420,
  leads: 124,
  conversion: 8.2,
  delta: 12.4,
};

export const TOKEN_USAGE = {
  total: 6820,
  limit: 10000,
  cycleSpend: 42.18,
  models: [
    { id: "gpt5", name: "GPT-5", tokens: 2840, share: 42, tone: "accent" },
    { id: "claude", name: "Claude Sonnet", tokens: 1980, share: 29, tone: "primary" },
    { id: "gemini", name: "Gemini 3 Flash", tokens: 1240, share: 18, tone: "warning" },
    { id: "gpt5mini", name: "GPT-5 Mini", tokens: 760, share: 11, tone: "chart-4" },
  ],
};

export const USAGE = {
  plan: "Growth",
  aiUsage: { used: 6820, limit: 10000 },
  conversations: { used: 12420, limit: 20000 },
  team: { used: 4, limit: 10 },
  spend: 42.18,
};

// ---- Module-level data ----

export const CONVERSATIONS = [
  { id: "c1", customer: "Layla Hassan", channel: "whatsapp", preview: "Hi, is the linen shirt available in size M?", status: "waiting", ai: true, time: "2m", unread: 2 },
  { id: "c2", customer: "Omar Khalid", channel: "instagram", preview: "Can I get a discount if I order 3?", status: "approval", ai: true, time: "6m", unread: 1 },
  { id: "c3", customer: "Noura Ali", channel: "whatsapp", preview: "Thank you! The order arrived today.", status: "resolved", ai: true, time: "18m", unread: 0 },
  { id: "c4", customer: "Sami Tariq", channel: "messenger", preview: "What are your delivery options to Jeddah?", status: "ai", ai: true, time: "24m", unread: 0 },
  { id: "c5", customer: "Huda Mansour", channel: "webchat", preview: "I'd like to return my last order.", status: "waiting", ai: false, time: "31m", unread: 3 },
  { id: "c6", customer: "Yousef Adel", channel: "whatsapp", preview: "Do you have the brass lamp in gold?", status: "ai", ai: true, time: "44m", unread: 0 },
  { id: "c7", customer: "Mariam Saleh", channel: "instagram", preview: "Following up on my order #2048.", status: "resolved", ai: true, time: "1h", unread: 0 },
  { id: "c8", customer: "Khalid Nasser", channel: "telegram", preview: "Is the wool throw machine-washable?", status: "ai", ai: true, time: "1h", unread: 0 },
];

export const CUSTOMERS = [
  { id: "u1", name: "Layla Hassan", channel: "whatsapp", orders: 7, spent: 1840, status: "active", lastSeen: "2m ago" },
  { id: "u2", name: "Omar Khalid", channel: "instagram", orders: 3, spent: 620, status: "lead", lastSeen: "6m ago" },
  { id: "u3", name: "Noura Ali", channel: "whatsapp", orders: 12, spent: 3980, status: "vip", lastSeen: "18m ago" },
  { id: "u4", name: "Sami Tariq", channel: "messenger", orders: 1, spent: 140, status: "lead", lastSeen: "24m ago" },
  { id: "u5", name: "Huda Mansour", channel: "webchat", orders: 5, spent: 1120, status: "active", lastSeen: "31m ago" },
  { id: "u6", name: "Yousef Adel", channel: "whatsapp", orders: 9, spent: 2410, status: "vip", lastSeen: "44m ago" },
  { id: "u7", name: "Mariam Saleh", channel: "instagram", orders: 4, spent: 880, status: "active", lastSeen: "1h ago" },
  { id: "u8", name: "Khalid Nasser", channel: "telegram", orders: 2, spent: 360, status: "active", lastSeen: "1h ago" },
];

export const ORDERS = [
  { id: "2048", customer: "Mariam Saleh", channel: "instagram", items: 2, total: 580, status: "fulfilled", date: "Sep 28" },
  { id: "2047", customer: "Yousef Adel", channel: "whatsapp", items: 1, total: 240, status: "processing", date: "Sep 28" },
  { id: "2046", customer: "Layla Hassan", channel: "whatsapp", items: 3, total: 920, status: "processing", date: "Sep 27" },
  { id: "2045", customer: "Noura Ali", channel: "whatsapp", items: 5, total: 1640, status: "follow-up", date: "Sep 26" },
  { id: "2044", customer: "Huda Mansour", channel: "webchat", items: 1, total: 140, status: "fulfilled", date: "Sep 26" },
  { id: "2043", customer: "Sami Tariq", channel: "messenger", items: 2, total: 410, status: "follow-up", date: "Sep 25" },
  { id: "2042", customer: "Omar Khalid", channel: "instagram", items: 1, total: 220, status: "fulfilled", date: "Sep 25" },
];

export const PRODUCTS = [
  { id: "p1", name: "Linen Shirt — Sand", sku: "LS-SAND", price: 295, stock: 96, status: "in-stock", trend: 14 },
  { id: "p2", name: "Ceramic Pour-Over Set", sku: "CPO-SET", price: 310, stock: 64, status: "in-stock", trend: 9 },
  { id: "p3", name: "Wool Throw — Stone", sku: "WT-STONE", price: 273, stock: 52, status: "in-stock", trend: -3 },
  { id: "p4", name: "Brass Desk Lamp", sku: "BD-LAMP", price: 424, stock: 28, status: "low", trend: 22 },
  { id: "p5", name: "Cotton Robe — Clay", sku: "CR-CLAY", price: 180, stock: 0, status: "out", trend: 0 },
  { id: "p6", name: "Oak Cutting Board", sku: "OC-BOARD", price: 96, stock: 14, status: "low", trend: 6 },
  { id: "p7", name: "Glass Carafe — 1L", sku: "GC-1L", price: 58, stock: 0, status: "out", trend: 0 },
  { id: "p8", name: "Leather Card Holder", sku: "LCH-TAN", price: 120, stock: 210, status: "in-stock", trend: 4 },
];

export const CAMPAIGNS = [
  { id: "m1", name: "Autumn Launch", channel: "whatsapp", status: "active", revenue: 9200, leads: 48, conversion: 9.4 },
  { id: "m2", name: "Ramadan Repeat", channel: "instagram", status: "active", revenue: 6400, leads: 52, conversion: 7.8 },
  { id: "m3", name: "VIP Restock Alert", channel: "email", status: "active", revenue: 2820, leads: 24, conversion: 6.1 },
  { id: "m4", name: "Summer Clearance", channel: "instagram", status: "ended", revenue: 14200, leads: 180, conversion: 5.2 },
];

export const AI_AGENTS = [
  { id: "a1", name: "Sales Concierge", status: "active", handled: 1284, automation: 89, handovers: 84 },
  { id: "a2", name: "Support Assistant", status: "active", handled: 558, automation: 82, handovers: 42 },
];

export const CHANNELS = [
  { id: "whatsapp", label: "WhatsApp", connected: true },
  { id: "instagram", label: "Instagram", connected: true },
  { id: "messenger", label: "Messenger", connected: true },
  { id: "telegram", label: "Telegram", connected: true },
  { id: "webchat", label: "Webchat", connected: true },
];

// Currency formatting is locale-aware and lives in the regional layer.
// Re-exported here so existing imports keep working.
export { formatCurrency } from "@/lib/regional";
