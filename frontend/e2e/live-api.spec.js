import { readFileSync } from "node:fs";
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

test("a per-line discount is stored on its line, so returning that one item refunds what it paid (50, not an even 75)", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  await mk("A", bcA); await mk("B", bcB);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "0.00" });

  await page.goto("/cashier/pos", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  const field = page.getByLabel("باركود المنتج").first();
  for (const bc of [bcA, bcB]) { await field.fill(bc); await field.press("Enter"); }
  await expect(main).toContainText(`ItemA ${sfx}`); await expect(main).toContainText(`ItemB ${sfx}`);
  await page.getByLabel(`نسبة الخصم على ItemA ${sfx}`).fill("50");
  await expect(main).toContainText("150.00", { timeout: 8000 }); // 200 - 50 = 150 is the quote the server gave
  await main.getByRole("button", { name: /\(F2\)/ }).click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.getByText("إتمام عملية البيع")).toBeVisible();
  await dlg.getByRole("button", { name: /تأكيد البيع/ }).click();
  await expect(dlg.getByText("معاينة الفاتورة")).toBeVisible();
  await page.keyboard.press("Escape");

  // The server's own record of the sale: the 50% sits on line A only, B has none.
  const rcpts = await api("GET", `/pos/sessions/${shift.id}/receipts`);
  const sale = rcpts.find((x) => x.kind === "sale");
  const detail = await api("GET", `/pos/receipts/${sale.id}`);
  expect(Number(detail.order.grand_total)).toBe(150);
  const paidA = detail.lines.find((l) => l.title.includes("ItemA"));
  expect(Number(paidA.total), "the 50% belongs to line A alone").toBe(50);
  expect(Number(detail.lines.find((l) => l.title.includes("ItemB")).total), "line B kept its full price").toBe(100);
  // Return ONLY line A through the API the returns screen uses: it must refund what A paid (50), not 75.
  const lineA = detail.lines.find((l) => l.title.includes("ItemA"));
  const ret = await api("POST", `/pos/sessions/${shift.id}/returns`, { order_id: sale.order_id ?? detail.order.id, lines: [{ variant_id: lineA.variant_id, quantity: 1 }], restock: true });
  expect(Number(ret.refunded_total), "returning the discounted item refunds what it paid").toBe(50);
  expect(errs).toEqual([]);
});

test("a fixed invoice discount can only take what the line discounts left, and the sale still goes through", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  await mk("A", bcA); await mk("B", bcB);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "0.00" });

  await page.goto("/cashier/pos", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  const field = page.getByLabel("باركود المنتج").first();
  await field.fill(bcA); await field.press("Enter");
  await expect(main).toContainText(`ItemA ${sfx}`);
  await page.getByLabel(`نسبة الخصم على ItemA ${sfx}`).fill("60");
  await expect(main).toContainText("40.00", { timeout: 8000 });
  const amt = page.locator("#invoice-discount-amount");
  await amt.fill("100"); await page.waitForTimeout(1500);
  await expect(amt, "100 asked, only 40 was left after the 60% line discount").toHaveValue("40");
  const pay = main.getByRole("button", { name: /\(F2\)/ });
  await expect(pay, "the cashier is not stuck: the sale can still be paid").toBeEnabled();
});

test("a return retried with a different quantity gets a new Idempotency-Key (never the failed attempt's)", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "0.00" });

  const sale = await api("POST", `/pos/sessions/${shift.id}/sell`, { items: [{ variant_id: vA.id, quantity: 3 }], tenders: [{ method: "cash", amount: "300.00" }], tenderedCash: "300.00" });
  await page.goto("/cashier/returns", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  const seen = [];
  let failNext = true;
  await page.route(/\/pos\/sessions\/[^/]+\/returns$/, async (route) => {
    const req = route.request();
    if (req.method() !== "POST") return route.continue();
    seen.push({ key: req.headers()["idempotency-key"], body: req.postData() });
    if (failNext) { failNext = false; return route.abort("connectionreset"); }
    return route.continue();
  });
  const search = main.getByRole("textbox").first();
  await search.fill(sale.invoice_number ?? sale.receipt_number ?? ""); await search.press("Enter");
  await expect(main).toContainText(`ItemA ${sfx}`);
  await main.getByRole("button", { name: /^إرجاع Item/ }).first().click();
  const plus = main.getByRole("button", { name: /^زيادة كمية/ }).first();
  await plus.click(); await plus.click(); // return all 3
  await main.getByRole("button", { name: /اعتماد المرتجع/ }).first().click();
  await expect.poll(() => seen.length).toBe(1); // the network dropped this one
  // the cashier lowers the quantity and tries again
  await main.getByRole("button", { name: /^تقليل كمية/ }).first().click();
  await main.getByRole("button", { name: /اعتماد المرتجع/ }).first().click();
  await expect.poll(() => seen.length).toBe(2);
  expect(seen[0].body, "the cashier changed the quantity, so it is a different return").not.toBe(seen[1].body);
  expect(seen[0].key, "a different return must not reuse the failed attempt's key").not.toBe(seen[1].key);
});

test("closing a shift on the screen: the expected cash is the ledger's (float + cash sales - cash expenses), a short count is recorded as a shortage, and the shift closes once", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "500.00" });

  // cash in: one sale of 100; cash out: one expense of 25. Expected in the drawer = 500 + 100 - 25 = 575.
  await api("POST", `/pos/sessions/${shift.id}/sell`, { items: [{ variant_id: vA.id, quantity: 1 }], tenders: [{ method: "cash", amount: "100.00" }], tenderedCash: "100.00" });
  const categories = await api("GET", "/expenses/categories");
  const category = (Array.isArray(categories) ? categories : categories.items ?? [])[0];
  await api("POST", "/expenses", { category_id: category.id, description: `Close ${sfx}`, amount: "25.00", payment_method: "cash", session_id: shift.id });
  const preview = await api("GET", `/pos/sessions/${shift.id}/close-preview`);
  const cashRow = preview.by_method.find((m) => m.method === "cash");
  expect(Number(cashRow.expected), "the ledger's expected cash: 500 float + 100 sale - 25 expense").toBe(575);

  await page.goto("/cashier/shifts", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  await main.getByRole("button", { name: "إغلاق الوردية" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog, "the dialog shows the ledger's expected cash, not a client guess").toContainText("575.00", { timeout: 10000 });
  await dialog.locator('input[type="number"]').fill("570"); // 5 short
  const shortage = dialog.locator("div", { hasText: /^فرق عجز/ }).last();
  await expect(shortage, "the screen names the gap a shortage of exactly 5.00").toContainText("-5.00");
  await expect(dialog).not.toContainText("فرق زيادة");
  await dialog.getByRole("button", { name: /تأكيد إغلاق الوردية/ }).click();
  await expect(page.getByText(/تم إغلاق الوردية/)).toBeVisible({ timeout: 10000 });

  const closed = await api("GET", `/pos/sessions/${shift.id}`);
  expect(String(closed.status).toLowerCase(), "the shift is closed on the server").toBe("closed");
  expect(Number(closed.counted_cash ?? closed.closing_cash), "the count we typed was stored").toBe(570);
  expect(Number(closed.variance ?? closed.cash_variance), "the shortage was stored as -5").toBe(-5);
  // a closed shift takes no more sales
  await expect(api("POST", `/pos/sessions/${shift.id}/sell`, { items: [{ variant_id: vA.id, quantity: 1 }], tenders: [{ method: "cash", amount: "100.00" }], tenderedCash: "100.00" })).rejects.toThrow();
});

test("an exchange on the screen: one A comes back, one B (price 150) goes out, the customer pays the 50 difference and the shelves follow", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA); const vB = await mk("B", bcB);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "0.00" });

  const onHand = async (variantId) => {
    const body = await api("GET", "/pos/stock?limit=100");
    const rows = Array.isArray(body) ? body : body.items ?? [];
    const row = rows.find((r) => r.variant_id === variantId);
    return row ? Number(row.on_hand ?? row.quantity) : 0;
  };
  // B costs 150 (A is 100). Sell two A (200) so there is something to exchange.
  await api("PATCH", `/variants/${vB.id}`, { price: "150.00" });
  const sale = await api("POST", `/pos/sessions/${shift.id}/sell`, { items: [{ variant_id: vA.id, quantity: 2 }], tenders: [{ method: "cash", amount: "200.00" }], tenderedCash: "200.00" });
  expect(await onHand(vA.id), "after selling 2 of 10 A").toBe(8);
  expect(await onHand(vB.id)).toBe(10);

  await page.goto("/cashier/exchanges", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  const search = page.getByLabel("بحث عن الفاتورة الأصلية");
  await search.fill(sale.invoice_number ?? sale.receipt_number ?? ""); await search.press("Enter");
  await expect(main).toContainText(`ItemA ${sfx}`, { timeout: 10000 });
  await main.getByRole("button", { name: /^إرجاع Item/ }).first().click(); // one A comes back (starts at 1)
  const repl = page.getByLabel("بحث عن المنتج البديل");
  await repl.fill(bcB); // a scanned barcode: the product list carries none, the stock view does
  await repl.press("Enter");
  await expect(main).toContainText(`ItemB ${sfx}`, { timeout: 10000 });
  await expect(main, "the server quote: B 150 - A 100 = 50 for the customer to pay").toContainText("50.00", { timeout: 10000 });
  await main.getByRole("button", { name: /إتمام الاستبدال/ }).click();
  const pay = page.getByRole("dialog");
  await expect(pay, "the difference is asked from the customer").toContainText("50.00", { timeout: 10000 });
  await pay.getByLabel("المبلغ المدفوع").fill("50");
  await pay.getByRole("button", { name: /تأكيد/ }).click();
  await expect(page.getByText(/تم اعتماد|تم الاستبدال|تم إتمام/).first()).toBeVisible({ timeout: 10000 });

  await expect.poll(() => onHand(vA.id), { message: "the returned A goes back on the shelf: 8 -> 9" }).toBe(9);
  await expect.poll(() => onHand(vB.id), { message: "the new B leaves the shelf: 10 -> 9" }).toBe(9);
  expect(errs).toEqual([]);
});

test("a supplier return on the screen: the goods leave the shelf at once, and a refusal by the supplier puts them back", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "0.00" });

  const onHand = async () => {
    const stock = await api("GET", "/pos/stock?limit=100");
    const row = (Array.isArray(stock) ? stock : stock.items ?? []).find((r) => r.variant_id === vA.id);
    return row ? Number(row.on_hand ?? row.quantity) : 0;
  };
  const supplier = await api("POST", "/suppliers", { name: `Supplier ${sfx}` });
  expect(await onHand(), "mk() put 10 on the shelf").toBe(10);

  await page.goto("/cashier/supplier-returns", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  await main.getByRole("button", { name: /تسجيل مرتجع للمورد/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox").first().click(); // the supplier
  await page.getByRole("option", { name: `Supplier ${sfx}` }).click();
  await dialog.getByPlaceholder("ابحث بالاسم أو الباركود أو الكود").fill(bcA); // by barcode: the shop scans, it does not type names
  await dialog.getByRole("button", { name: new RegExp(`ItemA ${sfx}`) }).first().click();
  await dialog.locator('input[inputmode="numeric"]').fill("2"); // الكمية المرتجعة
  await dialog.getByPlaceholder("0.00").fill("40");
  await dialog.getByRole("button", { name: "تسجيل المرتجع" }).click();
  await expect(page.getByText(/تم تسجيل|تم/).first()).toBeVisible({ timeout: 10000 });

  await expect.poll(onHand, { message: "the goods left the shelf the moment the return was recorded: 10 -> 8" }).toBe(8);
  await expect(main, "the return waits for the supplier's decision").toContainText("قبول", { timeout: 10000 });

  await main.getByRole("button", { name: "رفض" }).first().click();
  await expect.poll(onHand, { message: "a refusal puts the goods back on the shelf: 8 -> 10" }).toBe(10);

  // A second return, this time the supplier ACCEPTS: the goods stay gone and the money moves.
  await main.getByRole("button", { name: /تسجيل مرتجع للمورد/ }).click();
  const second = page.getByRole("dialog");
  await second.getByRole("combobox").first().click();
  await page.getByRole("option", { name: `Supplier ${sfx}` }).click();
  await second.getByPlaceholder("ابحث بالاسم أو الباركود أو الكود").fill(`ItemA ${sfx}`);
  await second.getByRole("button", { name: new RegExp(`ItemA ${sfx}`) }).first().click();
  await second.locator('input[inputmode="numeric"]').fill("3");
  await second.getByPlaceholder("0.00").fill("40");
  await second.getByRole("button", { name: "تسجيل المرتجع" }).click();
  await expect.poll(onHand, { message: "3 more left the shelf: 10 -> 7" }).toBe(7);
  await main.getByRole("button", { name: "قبول" }).first().click();
  await expect(main, "accepted: the supplier owes 3 x 40 = 120").toContainText("120.00", { timeout: 10000 });
  expect(await onHand(), "an acceptance must NOT put the goods back").toBe(7);
  expect(errs).toEqual([]);
});

test("a purchase on the screen: scanned barcode, 5 x 30 received, the shelf grows by 5 and the invoice total is 150", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "0.00" });

  const onHand = async () => {
    const stock = await api("GET", "/pos/stock?limit=100");
    const row = (Array.isArray(stock) ? stock : stock.items ?? []).find((r) => r.variant_id === vA.id);
    return row ? Number(row.on_hand ?? row.quantity) : 0;
  };
  await api("POST", "/suppliers", { name: `Supplier ${sfx}` });
  expect(await onHand(), "mk() put 10 on the shelf").toBe(10);

  await page.goto("/cashier/purchases", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  await main.getByRole("button", { name: /تسجيل توريد جديد/ }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox").first().click();
  await page.getByRole("option", { name: `Supplier ${sfx}` }).click();
  await dialog.getByPlaceholder("ابحث بالاسم أو الباركود أو الكود").fill(bcA); // the shop scans the box
  await dialog.getByRole("button", { name: new RegExp(`ItemA ${sfx}`) }).first().click();
  await dialog.getByPlaceholder("الكمية").fill("5");
  await dialog.getByPlaceholder("سعر الشراء").fill("30");
  await dialog.getByRole("button", { name: "إضافة" }).click();
  await expect(dialog, "the invoice total is 5 x 30").toContainText("150.00");
  await dialog.getByRole("button", { name: "حفظ واستلام البضاعة" }).click();
  await expect.poll(onHand, { message: "receiving the invoice puts the 5 on the shelf: 10 -> 15" }).toBe(15);
  await expect(main, "the new invoice is listed").toContainText(`Supplier ${sfx}`, { timeout: 10000 });
  expect(errs).toEqual([]);
});

test("paying a supplier on the screen: 180 owed, 100 paid in cash leaves the drawer and 80 stays owed", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "0.00" });

  const supplier = await api("POST", "/suppliers", { name: `Supplier ${sfx}` });
  const po = await api("POST", "/purchase-orders", { supplier_id: supplier.id, warehouse_id: wh.id, lines: [{ variant_id: vA.id, quantity: "6", unit_cost: "30.00" }], receive_now: true });
  expect(po.id, "the 180 invoice exists and is received").toBeTruthy();
  const cashOut = async () => Number((await api("GET", `/pos/sessions/${shift.id}/close-preview`)).cash_out);
  expect(await cashOut(), "nothing has left the drawer yet").toBe(0);

  await page.goto("/cashier/suppliers", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  await expect(main, "the supplier shows the 180 it is owed").toContainText("180.00", { timeout: 10000 });
  await main.getByRole("button", { name: /السجل/ }).first().click();
  const history = page.getByRole("dialog");
  await history.getByRole("button", { name: "دفع", exact: true }).first().click();
  const pay = page.getByRole("dialog").last();
  await pay.getByPlaceholder("0.00").fill("100");
  await pay.getByRole("button", { name: "تسجيل الدفعة" }).click();
  await expect.poll(cashOut, { message: "100 cash paid to the supplier leaves the drawer" }).toBe(100);

  await page.reload({ waitUntil: "networkidle" });
  await expect(page.locator("main:has(.cashier-root)"), "180 - 100 = 80 still owed").toContainText("80.00", { timeout: 10000 });
  expect(errs).toEqual([]);
});

test("a stocktake on the screen: counted 7 of the 10 it started with is 3 missing, and the sale made while counting is kept (10 - 1 sold - 3 missing = 6)", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "0.00" });

  const onHand = async () => {
    const stock = await api("GET", "/pos/stock?limit=100");
    const row = (Array.isArray(stock) ? stock : stock.items ?? []).find((r) => r.variant_id === vA.id);
    return row ? Number(row.on_hand ?? row.quantity) : 0;
  };
  expect(await onHand(), "mk() put 10 on the shelf").toBe(10);

  await page.goto("/cashier/inventory/stocktake", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  await main.getByRole("button", { name: "بدء جرد جديد" }).click();
  await expect(main.getByText(`ItemA ${sfx}`).first(), "the count sheet lists the item").toBeVisible({ timeout: 10000 });

  // a customer buys one while the shop is counting
  await api("POST", `/pos/sessions/${shift.id}/sell`, { items: [{ variant_id: vA.id, quantity: 1 }], method: "cash", amount: "100.00" });
  expect(await onHand(), "the sale took one off the shelf").toBe(9);

  const row = main.locator("tr", { hasText: `ItemA ${sfx}` }).first();
  await row.getByPlaceholder("لم يُعدّ").fill("7");
  // the difference is against the 10 the sheet started with, not against the 9 left after the sale
  await expect(row, "3 missing against the sheet's opening 10").toContainText("-3");
  await main.getByRole("button", { name: /اعتماد التسوية/ }).click();
  await expect.poll(onHand, { message: "the sale is kept and the 3 missing come off: 9 - 3 = 6, never 7 (which would erase the sale)" }).toBe(6);
  expect(errs).toEqual([]);
});

test("the reports on the screen: 3 sold, 1 returned, 25 spent in cash gives net sales 200 and 675 expected in the drawer", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "500.00" });

  // cash in: 3 x 100 sold; cash out: 1 x 100 returned, 25 spent. Net sales 200; drawer = 500 + 300 - 100 - 25 = 675.
  const sale = await api("POST", `/pos/sessions/${shift.id}/sell`, { items: [{ variant_id: vA.id, quantity: 3 }], tenders: [{ method: "cash", amount: "300.00" }], tenderedCash: "300.00" });
  const detail = sale.order_id ? null : sale;
  await api("POST", `/pos/sessions/${shift.id}/returns`, { order_id: sale.order_id ?? detail.order.id, lines: [{ variant_id: vA.id, quantity: 1 }], restock: true });
  const categories = await api("GET", "/expenses/categories");
  const category = (Array.isArray(categories) ? categories : categories.items ?? [])[0];
  await api("POST", "/expenses", { category_id: category.id, description: `Rep ${sfx}`, amount: "25.00", payment_method: "cash", session_id: shift.id });

  await page.goto("/cashier/reports", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  await expect(main, "net sales = 300 sold - 100 returned").toContainText("200.00", { timeout: 10000 });
  await expect(main, "3 pieces were sold").toContainText("3 قطعة");
  await main.getByRole("tab", { name: /إغلاق اليوم/ }).click();
  await expect(main, "the Z report expects 500 + 300 - 100 - 25 in the drawer").toContainText("675.00", { timeout: 10000 });
  expect(errs).toEqual([]);
});

test("the activity log on the screen: a sale, a return and an expense all appear, search isolates the expense, and the return filter hides the sale", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "500.00" });

  const sale = await api("POST", `/pos/sessions/${shift.id}/sell`, { items: [{ variant_id: vA.id, quantity: 2 }], tenders: [{ method: "cash", amount: "200.00" }], tenderedCash: "200.00" });
  await api("POST", `/pos/sessions/${shift.id}/returns`, { order_id: sale.order_id ?? sale.order.id, lines: [{ variant_id: vA.id, quantity: 1 }], restock: true });
  const categories = await api("GET", "/expenses/categories");
  const category = (Array.isArray(categories) ? categories : categories.items ?? [])[0];
  const note = `Zq${sfx}`;
  await api("POST", "/expenses", { category_id: category.id, description: note, amount: "25.00", payment_method: "cash", session_id: shift.id });

  await page.goto("/cashier/activity-log", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  await expect(main.getByText(note).first(), "the expense is in the timeline").toBeVisible({ timeout: 10000 });
  await expect(main.getByText("فاتورة بيع").first(), "the sale invoice is in the timeline").toBeVisible();
  await expect(main.getByText("مرتجع عميل").first(), "the return is in the timeline").toBeVisible();

  // searching the expense's own text leaves only that row
  await main.getByPlaceholder(/POS-RET/).fill(note);
  await expect(main.getByText(note).first()).toBeVisible();
  await expect(main.getByText("مرتجع عميل"), "search hides the return").toHaveCount(0, { timeout: 10000 });
  await main.getByPlaceholder(/POS-RET/).fill("");

  // the type filter: only customer returns
  await main.getByRole("combobox").first().click();
  await page.getByRole("option", { name: "مرتجع عميل" }).click();
  await expect(main.getByText("مرتجع عميل").first()).toBeVisible({ timeout: 10000 });
  await expect(main.getByText(note), "the return filter hides the expense").toHaveCount(0, { timeout: 10000 });
  await expect(main.getByText("فاتورة بيع"), "the return filter hides the sale invoice").toHaveCount(0);
  expect(errs).toEqual([]);
});

test("labels on the screen: 3 labels for an item show its real barcode and price, and the preview counts exactly 3", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "500.00" });

  await page.goto("/cashier/labels", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  await main.getByPlaceholder(/SKU-0001/).fill(bcA);
  const qty = main.getByLabel(/عدد الملصقات لكل متغير/);
  await expect(qty, "the search finds the item by its barcode").toHaveCount(1, { timeout: 10000 });
  await qty.fill("3");
  await main.getByRole("button", { name: /معاينة وطباعة 3 ملصق/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(bcA, { exact: true }), "3 labels, each with the item's real barcode").toHaveCount(3, { timeout: 10000 });
  await expect(dialog.getByText("100.00", { exact: false }), "each label carries the real price").toHaveCount(3);
  expect(errs).toEqual([]);
});

test("backup export on the screen: the downloaded file holds the real expense and product, and says nothing is truncated", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "500.00" });

  const categories = await api("GET", "/expenses/categories");
  const category = (Array.isArray(categories) ? categories : categories.items ?? [])[0];
  const note = `Bk${sfx}`;
  await api("POST", "/expenses", { category_id: category.id, description: note, amount: "25.00", payment_method: "cash", session_id: shift.id });

  await page.goto("/settings/pos", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  await main.getByRole("tab", { name: /النسخ|الاحتياطي/ }).click();
  const [download] = await Promise.all([page.waitForEvent("download"), main.getByRole("button", { name: /تصدير الآن/ }).click()]);
  const file = JSON.parse(readFileSync(await download.path(), "utf8"));
  expect(file.failed_tables, "no table failed to export").toEqual([]);
  expect(file.truncated_tables, "a small shop is nowhere near the export caps").toEqual([]);
  expect(JSON.stringify(file.tables.expenses), "the real expense is in the file").toContain(note);
  expect(JSON.stringify(file.tables.stock), "the real item is in the stock").toContain(bcA);
  await expect(main.getByTestId("export-truncated")).toHaveCount(0);
  expect(errs).toEqual([]);
});

test("print settings on the screen do not pretend to save: no save button, no editable fields, and a clear notice", async ({ page }) => {
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  const sfx = `${Date.now()}`.slice(-8); const email = `ld-${sfx}@example.com`; const pw = `Ld-${sfx}-pass!`;
  await page.goto("/register");
  await page.getByLabel(/البريد الإلكتروني|email/i).fill(email);
  await page.getByLabel(/^كلمة المرور$|^password$/i).fill(pw);
  await page.getByLabel(/تأكيد كلمة المرور|confirm password/i).fill(pw);
  await page.getByRole("button", { name: /إنشاء الحساب|create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const api = (method, path, body) => page.evaluate(async ({ method, path, body }) => {
    const raw = JSON.parse(localStorage.getItem("fihrist_tokens") || "null");
    const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) || [])[1];
    const h = { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(raw?.access_token ? { Authorization: `Bearer ${raw.access_token}` } : {}) };
    const r = await fetch(`/api/v1${path}`, { method, headers: h, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${t.slice(0, 200)}`); return t ? JSON.parse(t) : null;
  }, { method, path, body });
  const wh = await api("POST", "/warehouses/ensure-default");
  const mk = async (tag, bc) => {
    const p = await api("POST", "/products", { title: `Item${tag} ${sfx}`, slug: `item-${tag}-${sfx}`, description: null });
    const v = await api("POST", `/products/${p.id}/variants`, { sku: `LD${tag}-${sfx}`, price: "100.00", option_values: {} });
    await api("POST", `/variants/${v.id}/identifiers`, { identifier_type: "barcode", value: bc });
    await api("POST", "/inventory/movements", { variant_id: v.id, warehouse_id: wh.id, direction: "in", quantity: 10, reason: "adjustment" });
    await api("PATCH", `/products/${p.id}`, { status: "active" }); return v;
  };
  const bcA = `630${sfx}1`, bcB = `630${sfx}2`;
  const vA = await mk("A", bcA);
  const profile = await api("POST", "/pos/profiles", { name: "Main", code: "MAIN", warehouse_id: wh.id, allowed_payment_methods: ["cash"], default_payment_method: "cash" });
  const reg = await api("POST", "/pos/registers", { name: "Till", code: "MAIN", warehouse_id: wh.id, profile_id: profile.id });
  const shift = await api("POST", `/pos/registers/${reg.id}/sessions`, { opening_float: "500.00" });

  await page.goto("/settings/pos", { waitUntil: "networkidle" });
  const main = page.locator("main:has(.cashier-root)");
  await main.getByRole("tab", { name: /الفاتورة|الباركود|الطباعة/ }).click();
  await expect(main.getByTestId("print-not-stored"), "it says plainly that nothing is stored").toBeVisible({ timeout: 10000 });
  await expect(main.getByRole("button", { name: /^حفظ$/ }), "no save button that would claim a save that never happens").toHaveCount(0);
  await expect(main.getByRole("textbox"), "no editable receipt field that is thrown away").toHaveCount(0);
  expect(errs).toEqual([]);
});
