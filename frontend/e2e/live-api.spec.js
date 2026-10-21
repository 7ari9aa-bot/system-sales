import { expect, test } from "@playwright/test";

test.skip(process.env.E2E_LIVE_API !== "1", "requires the ephemeral API/Postgres/Redis CI stack");

test("real registration, dashboard reads, orders, and logout work end to end", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  const email = `live-e2e-${suffix}@example.com`;
  const password = `Live-e2e-${suffix}!`;

  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(password);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(password);

  const registerResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/auth/register" && response.request().method() === "POST";
  });
  const loginResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/auth/login" && response.request().method() === "POST";
  });
  const dashboardResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/analytics/dashboard" && response.request().method() === "GET";
  });

  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();

  const registerResponse = await registerResponsePromise;
  // Register answers a neutral 202 (email-verification wave): the body never
  // distinguishes a fresh address from a taken one, and no session comes back
  // with it. The page's own flow is register -> login, and an UNVERIFIED
  // account can still sign in (verification gates invitation binding only),
  // so the assertions below stay: login 200, then the real dashboard reads.
  expect(registerResponse.status(), await registerResponse.text()).toBe(202);
  expect((await loginResponsePromise).status()).toBe(200);
  await expect(page).toHaveURL(/\/dashboard$/);

  const dashboardResponse = await dashboardResponsePromise;
  expect(dashboardResponse.status()).toBe(200);
  const dashboard = await dashboardResponse.json();
  expect(dashboard).toEqual(expect.objectContaining({
    orders: expect.any(Object),
    conversations: expect.any(Object),
    daily_orders: expect.any(Array),
    revenue_by_source: expect.any(Array),
  }));
  // The delivered theme moved sign-out into the account dropdown — the item
  // exists only while the menu is open, so assert it through the trigger.
  await page.getByRole("button", { name: /قائمة الحساب|account menu/i }).click();
  await expect(page.getByRole("menuitem", { name: /تسجيل الخروج|sign out/i })).toBeVisible();
  await page.keyboard.press("Escape");

  const ordersResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/orders"
      && url.searchParams.get("limit") === "100"
      && response.request().method() === "GET";
  });
  await page.getByRole("navigation").locator('a[href="/orders"]').click();
  await expect(page).toHaveURL(/\/orders$/);
  const ordersResponse = await ordersResponsePromise;
  expect(ordersResponse.status()).toBe(200);
  expect(await ordersResponse.json()).toEqual(expect.objectContaining({ items: expect.any(Array) }));

  const logoutResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/auth/logout" && response.request().method() === "POST";
  });
  await page.getByRole("button", { name: /قائمة الحساب|account menu/i }).click();
  await page.getByRole("menuitem", { name: /تسجيل الخروج|sign out/i }).click();
  expect((await logoutResponsePromise).status()).toBe(204);
  // v7 note: after logout the guard's redirect wins — /login?returnTo=<where you were>.
  await expect(page).toHaveURL(/\/login(\?|$)/);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("fihrist_tokens"))).toBeNull();

  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?returnTo=/);
  expect(pageErrors).toEqual([]);
});

// A full cashier sale against the REAL backend: the UI is the only thing under test, so the shop
// (warehouse, till, open shift, one stocked product) is prepared through the same endpoints the
// cashier screens use. This replaces the sale test that ran against a mocked API, which could only
// ever prove the mock.
test("a real sale: scan -> confirm -> receipt -> two sales get two invoice numbers and stock drops by two", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const email = `live-sale-${suffix}@example.com`;
  const password = `Live-sale-${suffix}!`;

  // Register + sign in through the UI so the session is exactly what a person gets.
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(password);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(password);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  // Prepare the shop from inside the page, so the app's own auth (token + CSRF) is used.
  const barcode = `620${Date.now().toString().slice(-9)}`;
  const setup = await page.evaluate(async ({ sfx, barcode }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const headers = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const call = async (method, path, body) => {
      const res = await fetch(`/api/v1${path}`, { method, headers, credentials: "include", body: body ? JSON.stringify(body) : undefined });
      const text = await res.text();
      if (!res.ok) throw new Error(`${method} ${path} -> ${res.status} ${text.slice(0, 160)}`);
      return text ? JSON.parse(text) : null;
    };
    const wh = await call("POST", "/warehouses/ensure-default");
    const product = await call("POST", "/products", { title: `Live item ${sfx}`, slug: `live-item-${sfx}`, description: null });
    const variant = await call("POST", `/products/${product.id}/variants`, { sku: `LIVE-${sfx}`, price: "100.00", option_values: {} });
    await call("POST", `/variants/${variant.id}/identifiers`, { identifier_type: "barcode", value: barcode });
    await call("POST", "/inventory/movements", { variant_id: variant.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await call("PATCH", `/products/${product.id}`, { status: "active" });
    const profile = await call("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash", "card", "wallet", "bank_transfer"], default_payment_method: "cash" });
    const register = await call("POST", "/pos/registers", { name: "Main till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
    await call("POST", `/pos/registers/${register.id}/sessions`, { opening_float: "0.00" });
    return { variantId: variant.id, warehouseId: wh.id };
  }, { sfx: suffix.replace(/[^a-z0-9]/gi, "").toLowerCase(), barcode });

  await page.goto("/cashier/pos", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  const barcodeField = page.getByLabel("باركود المنتج").first();

  // One real sale: scan -> F2 -> confirm. The invoice number is minted by the backend at confirm
  // time (the screen says "new invoice" until then), so read it from the receipt.
  const sell = async () => {
    await barcodeField.fill(barcode);
    await barcodeField.press("Enter");
    await expect(main).toContainText(/Live item/);
    await main.getByRole("button", { name: /\(F2\)/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("إتمام عملية البيع")).toBeVisible();
    await dialog.getByRole("button", { name: /تأكيد البيع/ }).click();
    await expect(dialog.getByText("معاينة الفاتورة")).toBeVisible();
    const number = ((await dialog.innerText()).match(/POS-\d{8}-[A-Z0-9]+/) || [""])[0];
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    return number;
  };

  const first = await sell();
  expect(first, "the receipt must carry the invoice number the backend issued").toMatch(/^POS-/);
  const second = await sell();
  expect(second).toMatch(/^POS-/);
  expect(second, "a second sale must get a new invoice number").not.toBe(first);

  // The backend, not the screen, is the witness that stock actually left the shelf.
  const onHand = await page.evaluate(async ({ variantId }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const res = await fetch(`/api/v1/pos/stock?limit=50`, { credentials: "include", headers: raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {} });
    const body = await res.json();
    const rows = Array.isArray(body) ? body : body.items ?? [];
    return rows.find((r) => r.variant_id === variantId || r.id === variantId)?.on_hand ?? rows.find((r) => r.variant_id === variantId)?.quantity ?? null;
  }, { variantId: setup.variantId });
  expect(Number(onHand)).toBe(8);
  expect(pageErrors).toEqual([]);
});

test("a real back-office day: supplier stock in -> cash expense -> stocktake approved; the backend ledger and the screens agree", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const email = `live-ops-${suffix}@example.com`;
  const password = `Live-ops-${suffix}!`;

  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(password);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(password);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  // Every call goes through the page, so the app's own token + CSRF are what the backend sees.
  const api = (method, path, body) =>
    page.evaluate(async ({ method, path, body }) => {
      const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
      const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
      const headers = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
      const res = await fetch(`/api/v1${path}`, { method, headers, credentials: "include", body: body ? JSON.stringify(body) : undefined });
      const text = await res.text();
      if (!res.ok) throw new Error(`${method} ${path} -> ${res.status} ${text.slice(0, 200)}`);
      return text ? JSON.parse(text) : null;
    }, { method, path, body });

  const sfx = suffix.replace(/[^a-z0-9]/gi, "").toLowerCase();
  const wh = await api("POST", "/warehouses/ensure-default");
  const product = await api("POST", "/products", { title: `Ops item ${sfx}`, slug: `ops-item-${sfx}`, description: null });
  const variant = await api("POST", `/products/${product.id}/variants`, { sku: `OPS-${sfx}`, price: "100.00", option_values: {} });
  await api("POST", `/variants/${variant.id}/identifiers`, { identifier_type: "barcode", value: `621${Date.now().toString().slice(-9)}` });
  await api("PATCH", `/products/${product.id}`, { status: "active" });
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const register = await api("POST", "/pos/registers", { name: "Main till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${register.id}/sessions`, { opening_float: "500.00" });

  const onHand = async () => {
    const body = await api("GET", "/pos/stock?limit=100");
    const rows = Array.isArray(body) ? body : body.items ?? [];
    const row = rows.find((r) => r.variant_id === variant.id);
    return row ? Number(row.on_hand ?? row.quantity) : 0;
  };

  // 1) Supplier stock in: 6 units at 40.50 -> shelf 0 -> 6, the invoice is still unpaid.
  const supplier = await api("POST", "/suppliers", { name: `Supplier ${sfx}` });
  const po = await api("POST", "/purchase-orders", { supplier_id: supplier.id, warehouse_id: wh.id, lines: [{ variant_id: variant.id, quantity: "6", unit_cost: "40.50" }], receive_now: true });
  expect(po.id, "the purchase order must be created").toBeTruthy();
  expect(await onHand(), "receiving the order puts the goods on the shelf").toBe(6);

  // 2) A cash expense rung against the open shift leaves the drawer by exactly its amount.
  const categories = await api("GET", "/expenses/categories");
  const category = (Array.isArray(categories) ? categories : categories.items ?? [])[0];
  expect(category, "the shop must come with at least one expense category").toBeTruthy();
  await api("POST", "/expenses", { category_id: category.id, description: `Cleaning ${sfx}`, amount: "25.00", payment_method: "cash", session_id: shift.id });
  const preview = await api("GET", `/pos/sessions/${shift.id}/close-preview`);
  expect(Number(preview.cash_out), "the expense is the only cash that left the drawer").toBe(25);

  // 3) Stocktake: the shelf really holds 4, not 6. Approving moves the book by -2, exactly once.
  const take = await api("POST", "/pos/stocktakes", { note: `count ${sfx}` });
  await api("PUT", `/pos/stocktakes/${take.id}/counts`, { counts: [{ variant_id: variant.id, counted_qty: 4 }] });
  await api("POST", `/pos/stocktakes/${take.id}/approve`, {});
  expect(await onHand(), "approving the count settles the book on what was counted").toBe(4);
  await api("POST", `/pos/stocktakes/${take.id}/approve`, {}).catch(() => {});
  expect(await onHand(), "approving again must not move stock a second time").toBe(4);

  // The screens a person opens must show what the ledger just recorded.
  for (const [path, needle] of [
    ["/cashier/expenses", `Cleaning ${sfx}`],
    ["/cashier/purchases", `Supplier ${sfx}`],
    ["/cashier/suppliers", `Supplier ${sfx}`],
    ["/cashier/inventory", `Ops item ${sfx}`],
  ]) {
    await page.goto(path, { waitUntil: "networkidle" });
    await expect(page.locator("main:has(.cashier-root)"), `${path} must show ${needle}`).toContainText(needle, { timeout: 10000 });
  }
  expect(pageErrors).toEqual([]);
});
