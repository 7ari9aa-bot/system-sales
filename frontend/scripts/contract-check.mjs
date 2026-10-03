// Read-only contract smoke check against a test backend. Credentials and the
// target origin must be supplied by the operator; never commit test accounts.
const API = process.env.CONTRACT_API_ORIGIN || "http://127.0.0.1:8000";
const EMAIL = process.env.CONTRACT_LOGIN_EMAIL;
const PASSWORD = process.env.CONTRACT_LOGIN_PASSWORD;

if (!EMAIL || !PASSWORD) {
  console.error("Set CONTRACT_LOGIN_EMAIL and CONTRACT_LOGIN_PASSWORD for a test account.");
  process.exit(2);
}

const origin = new URL(API);
if (origin.protocol !== "https:" && origin.hostname !== "127.0.0.1" && origin.hostname !== "localhost") {
  console.error("CONTRACT_API_ORIGIN must use HTTPS outside localhost.");
  process.exit(2);
}

const REQUIRED = {
  "/auth/me": ["id", "email", "tenants"],
  "/analytics/dashboard": [
    "orders.orders_count", "orders.gross_revenue", "orders.refunded_amount",
    "orders.net_revenue", "orders.refund_excess", "orders.gross_aov",
    "orders.net_aov", "orders.currency", "orders.timezone",
    "ai_orders_30d", "conversations.open", "conversations.unread",
    "customers", "products_active", "low_stock_count",
    "out_of_stock_count", "daily_orders", "revenue_by_source",
  ],
  "/analytics/overview?days=30": [
    "currency", "timezone", "orders_count", "gross_revenue", "net_revenue",
    "net_aov", "daily_series", "stock.low_stock_count", "stock.out_of_stock_count",
  ],
  "/ai/usage/summary": ["summary", "totals.cost", "totals.tokens_in", "totals.tokens_out"],
  "/ai/approvals?status=PENDING": ["items", "truncated"],
  "/ai/agents": ["[is_active]", "[name]"],
  "/marketing/campaigns": ["items"],
  "/analytics/summary": ["orders_summary", "revenue_by_source", "revenue_by_campaign"],
  "/conversations?limit=50": ["items"],
  "/customers?limit=50": ["items", "items[].name", "items[].lifetime_value", "items[].is_blocked"],
  "/orders?limit=50": ["items", "items[].number", "items[].status", "items[].grand_total", "items[].currency"],
  "/products": ["[title]", "[status]"],
  "/inventory/balances": ["[]"],
  "/notifications": ["[]"],
  "/platform/health": ["status"],
  "/search?q=a&limit=8": ["[]"],
};

function get(obj, path) {
  return path.split(".").reduce((acc, k) => (acc == null ? undefined : acc[k]), obj);
}

const login = await fetch(`${origin.origin}/api/v1/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
}).then((r) => r.json());

const token = login.access_token;
if (!token) {
  console.log("LOGIN FAILED:", JSON.stringify(login).slice(0, 200));
  process.exit(1);
}
console.log("login: OK (bearer obtained)\n");

let failures = 0;
for (const [path, fields] of Object.entries(REQUIRED)) {
  let status = 0;
  let body = null;
  try {
    const res = await fetch(`${origin.origin}/api/v1${path.startsWith("/") ? path : "/" + path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    status = res.status;
    body = await res.json().catch(() => null);
  } catch (e) {
    console.log(`FAIL ${path} — network: ${e.message}`);
    failures++;
    continue;
  }
  if (status !== 200) {
    console.log(`FAIL ${path} — HTTP ${status}: ${JSON.stringify(body).slice(0, 120)}`);
    failures++;
    continue;
  }
  const missing = fields.filter((f) => {
    if (f.startsWith("[")) {
      // عنصر مصفوفة: افحص إن الرد مصفوفة فيها العناصر دي كحقول
      const arr = Array.isArray(body) ? body : null;
      if (!arr) return true;
      const key = f.slice(1, -1);
      return arr.length > 0 ? get(arr[0], key) === undefined && arr[0][key] === undefined : false;
    }
    return get(body, f) === undefined;
  });
  if (missing.length) {
    console.log(`PARTIAL ${path} — missing: ${missing.join(", ")}`);
    failures++;
  } else {
    console.log(`OK   ${path}`);
  }
}

console.log(`\nverdict: ${Object.keys(REQUIRED).length - failures}/${Object.keys(REQUIRED).length} endpoints fully match frontend expectations`);
process.exit(failures ? 1 : 0);
