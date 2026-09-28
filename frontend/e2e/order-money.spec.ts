import { expect, test } from "@playwright/test";
import type { Route } from "@playwright/test";
import { json, mockShell, seedAuth, seedLang } from "./support";
import { buildCreateOrderPayload, summarizeOrderMoney } from "../src/components/orders/order-request";
import { inputScale, parseMoney, renderMinor, STORAGE_SCALE } from "../src/components/orders/money";

/* The create-order dialog's money terms and its Idempotency-Key.
 *
 * CI-ONLY PROOF. This sandbox cannot bind a TCP port, so no browser ever ran
 * these specs here: they are typechecked and written against the routes they
 * mock. The five cases that never touch `page` run in Playwright's node worker
 * and exercise the SAME pure module the dialog imports, so the arithmetic claim
 * is verifiable even where the UI claim needs a runner.
 *
 * What is pinned down:
 *  - the money `CreateOrderRequest` accepts is validated client-side with the
 *    rules `money.py` enforces, and reaches the wire as strings;
 *  - an untouched form posts the byte-identical body this screen posted before
 *    the money inputs existed;
 *  - the displayed total is `subtotal − discount + shipping + tax`, computed on
 *    minor units (never float64), in the tenant's own currency;
 *  - one Idempotency-Key per OPENED dialog survives a retry, and a 409 stops the
 *    dialog instead of re-sending under a fresh key.
 */

const CUSTOMERS = {
  items: [
    {
      id: "cust-1",
      name: "Layla H.",
      phone: "+201000000001",
      email: null,
      lifetime_value: "250.00",
      is_blocked: false,
    },
  ],
};

// 120.00 and 0.10: the pair that breaks a float sum.
const PRODUCTS = [
  {
    id: "prod-1",
    title: "Coffee Beans",
    slug: "coffee-beans",
    status: "active",
    variants: [
      { id: "var-1", title: "250g", sku: "CB-250", price: "120.00" },
      { id: "var-2", title: "Sachet", sku: "CB-S", price: "0.10" },
    ],
  },
];

const CREATED_ORDER = {
  id: "o-new",
  number: "ORD-1002",
  status: "pending",
  subtotal: "120.00",
  discount_total: "10.00",
  shipping_total: "15.00",
  tax_total: "5.00",
  grand_total: "130.00",
  currency: "EGP",
};

/** The guard's exact 409 envelope (`core/idempotency._emit_error`). */
const CONFLICT_BODY = {
  error: {
    code: "conflict",
    message: "Idempotency-Key reused with a different request body",
    retryable: false,
    request_id: "req-1",
  },
};

type Sent = { body: string; key: string | null; headers: Record<string, string> };
/** The four answers the guard can give a guarded POST, straight out of
 *  `core/idempotency.py`: 2xx completes and replays, a 4xx RELEASES the key (a
 *  corrected retry may run), a 5xx marks it terminal-failed (a retry is refused
 *  with 409), and a reused key with a new body is a 409. */
type Outcome = "ok" | "conflict" | "replay" | "reject" | "poisoned" | "server_error";

/** Fulfil JSON with an extra header — the replay flag has no helper in
 *  `./support`, which stays shared with the other specs. */
function jsonWithReplayHeader(route: Route, body: unknown, status: number) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
    headers: { "idempotency-replayed": "true" },
  });
}

/** Mock the orders screen. `onCreate` is told which attempt this is (1 = the
 *  first POST of this dialog open), so a test can fail once and succeed next. */
async function mockOrdersApi(
  page: import("@playwright/test").Page,
  opts: { currency?: string | null; onCreate?: (attempt: number) => Outcome } = {},
): Promise<Sent[]> {
  const sent: Sent[] = [];
  await page.route("**/api/v1/customers**", (route) => json(route, CUSTOMERS));
  await page.route("**/api/v1/products**", (route) => json(route, PRODUCTS));
  if (opts.currency === null) {
    // The tenant-currency read FAILS: the dialog must fall back to two places
    // and show no code, rather than inventing a symbol.
    await page.route("**/api/v1/tenants/**/currency", (route) =>
      json(route, { error: { message: "currency unavailable" } }, 500),
    );
  } else {
    await page.route("**/api/v1/tenants/**/currency", (route) =>
      json(route, { tenant_id: "tenant-1", currency: opts.currency ?? "EGP" }),
    );
  }
  await page.route("**/api/v1/orders**", (route) => {
    const request = route.request();
    if (request.method() !== "POST") return json(route, { items: [], next_cursor: null });
    sent.push({
      body: request.postData() ?? "",
      key: request.headers()["idempotency-key"] ?? null,
      headers: request.headers(),
    });
    const outcome = opts.onCreate?.(sent.length) ?? "ok";
    if (outcome === "conflict") return json(route, CONFLICT_BODY, 409);
    if (outcome === "poisoned")
      // What `core/idempotency.py` really answers when an earlier attempt under
      // this key ended in a 5xx: the key is terminal, and only a new key (i.e.
      // a new dialog open) may run again.
      return json(
        route,
        {
          error: {
            code: "conflict",
            message:
              "previous attempt with this Idempotency-Key failed with an unknown outcome; retry with a new key",
            retryable: false,
          },
        },
        409,
      );
    if (outcome === "reject")
      // A 4xx: the route never ran, and the guard RELEASES the key, so a
      // corrected retry with the SAME key is legal.
      return json(
        route,
        { error: { code: "validation_error", message: "the warehouse refused the reservation", retryable: false } },
        400,
      );
    if (outcome === "server_error")
      return json(route, { error: { message: "upstream failure", code: "internal", retryable: true } }, 500);
    if (outcome === "replay") return jsonWithReplayHeader(route, CREATED_ORDER, 201);
    return json(route, CREATED_ORDER, 201);
  });
  return sent;
}

async function openDialogAndPickOne(page: import("@playwright/test").Page) {
  await page.getByTestId("toggle-order-form").click();
  await page.locator("#o-customer").selectOption("cust-1");
  await page.getByLabel("Products 1").selectOption("var-1");
}

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await mockShell(page);
  await seedLang(page, "en");
});

/* ------------------------------------------------- pure money module (node) */

test("money math: decimal strings in, exact minor units out — no float path", () => {
  // The float trap this module exists to close: 3×0.10 + 4×0.10 must read 0.70,
  // not 0.7000000000000001, and the total must not inherit the drift.
  const summary = summarizeOrderMoney({
    lines: [
      { variant_id: "var-2", quantity: 3 },
      { variant_id: "var-2", quantity: 4 },
    ],
    priceOf: (id) => (id === "var-2" ? "0.10" : undefined),
    money: { discount: "0.20", shipping: "0.05", tax: "0" },
    scale: 2,
  });
  expect(renderMinor(summary.subtotal, STORAGE_SCALE)).toBe("0.70");
  expect(renderMinor(summary.grand, STORAGE_SCALE)).toBe("0.55");
  expect(summary.valid).toBe(true);
});

test("money rules mirror the server: non-negative, never NaN, at most the currency exponent", () => {
  for (const text of ["-5", "-0.01", "1.234", "abc", "1e3", "12.", ".5", "1.2.3", "NaN", "Infinity", "١٢٣"]) {
    expect(parseMoney(text, 2).state, `${text} must be refused`).toBe("invalid");
  }
  expect(parseMoney("", 2).state).toBe("empty");
  expect(parseMoney("12.5", 2)).toEqual({ state: "ok", minor: 1250n, amount: "12.50" });

  // A yen tenant types whole yen; the scale comes from the ISO-4217 table.
  expect(inputScale("JPY")).toBe(0);
  expect(parseMoney("1.5", inputScale("JPY")).state).toBe("invalid");
  expect(parseMoney("1000", inputScale("JPY"))).toEqual({ state: "ok", minor: 100000n, amount: "1000.00" });
  // An unknown code answers 2 places, like `money.py:_exponent_for`; a
  // prototype key must not answer a function.
  expect(inputScale("XYZ")).toBe(2);
  expect(inputScale("constructor")).toBe(2);
  expect(inputScale(null)).toBe(2);
});

test("an untouched form builds exactly the body this screen posted before the money inputs", () => {
  const lines = [{ variant_id: "var-1", quantity: 2 }];
  const summary = summarizeOrderMoney({
    lines,
    priceOf: () => "120.00",
    money: { discount: "", shipping: "", tax: "" },
    scale: 2,
  });
  expect(JSON.stringify(buildCreateOrderPayload({ customerId: "cust-1", lines, summary }))).toBe(
    '{"customer_id":"cust-1","items":[{"variant_id":"var-1","quantity":2}],"channel":"dashboard"}',
  );
});

test("typed money is sent as normalized strings, and only for the fields typed", () => {
  const lines = [{ variant_id: "var-1", quantity: 1 }];
  const summary = summarizeOrderMoney({
    lines,
    priceOf: () => "120.00",
    money: { discount: "12.5", shipping: " 15 ", tax: "" },
    scale: 2,
  });
  expect(JSON.stringify(buildCreateOrderPayload({ customerId: "cust-1", lines, summary }))).toBe(
    '{"customer_id":"cust-1","items":[{"variant_id":"var-1","quantity":1}],"channel":"dashboard","discount_total":"12.50","shipping_total":"15.00"}',
  );
  expect(renderMinor(summary.grand, STORAGE_SCALE)).toBe("122.50");
});

test("a discount past the order total is refused locally, as compute_totals refuses it", () => {
  const summary = summarizeOrderMoney({
    lines: [{ variant_id: "var-1", quantity: 1 }],
    priceOf: () => "120.00",
    money: { discount: "121", shipping: "0", tax: "0" },
    scale: 2,
  });
  expect(summary.negativeTotal).toBe(true);
  expect(summary.valid).toBe(false);
});

/* ------------------------------------------------------------------ dialog */

test("the running total follows the server's formula and names the tenant currency", async ({ page }) => {
  await mockOrdersApi(page);
  await page.goto("/orders");
  await openDialogAndPickOne(page);

  await expect(page.getByTestId("order-grand-total")).toHaveText("120.00 EGP");

  await page.getByTestId("order-money-discount").fill("10");
  await page.getByTestId("order-money-shipping").fill("15");
  await page.getByTestId("order-money-tax").fill("5.5");

  // 120 − 10 + 15 + 5.50
  await expect(page.getByTestId("order-grand-total")).toHaveText("130.50 EGP");
  await expect(page.getByTestId("order-totals")).toContainText("−10.00 EGP");
  await expect(page.getByTestId("order-totals")).toContainText("+15.00 EGP");
  await expect(page.getByTestId("order-totals")).toContainText("+5.50 EGP");
});

test("an invalid term blocks the submit and names the rule it broke", async ({ page }) => {
  await mockOrdersApi(page);
  await page.goto("/orders");
  await openDialogAndPickOne(page);

  await page.getByTestId("order-money-discount").fill("-5");
  await expect(page.getByTestId("order-money-error-discount")).toBeVisible();
  await expect(page.getByTestId("submit-order")).toBeDisabled();

  await page.getByTestId("order-money-discount").fill("1.234");
  await expect(page.getByTestId("order-money-error-discount")).toContainText("at most 2 decimal");
  await expect(page.getByTestId("submit-order")).toBeDisabled();

  await page.getByTestId("order-money-discount").fill("10");
  await expect(page.getByTestId("order-money-error-discount")).toHaveCount(0);
  await expect(page.getByTestId("submit-order")).toBeEnabled();
});

test("the exponent is the tenant's, and a failed currency read falls back to two places", async ({ page }) => {
  await mockOrdersApi(page, { currency: "JPY" });
  await page.goto("/orders");
  await openDialogAndPickOne(page);
  await page.getByTestId("order-money-shipping").fill("1.5");
  await expect(page.getByTestId("order-money-error-shipping")).toBeVisible();
  await expect(page.getByTestId("submit-order")).toBeDisabled();
  await expect(page.getByTestId("order-grand-total")).toHaveText("120.00 JPY");

  await mockOrdersApi(page, { currency: null });
  await page.goto("/orders");
  await openDialogAndPickOne(page);
  // No code invented: the digits stand alone, exactly as `formatMoney` and
  // `money.py:_exponent_for` agree they should.
  await expect(page.getByTestId("order-grand-total")).toHaveText("120.00");
});

test("an untouched dialog posts the pre-money body byte-for-byte, with one idempotency key", async ({ page }) => {
  const sent = await mockOrdersApi(page);
  await page.goto("/orders");
  await openDialogAndPickOne(page);
  await page.getByTestId("submit-order").click();
  await expect(page.getByText("Order created", { exact: true })).toBeVisible();

  expect(sent).toHaveLength(1);
  expect(sent[0].body).toBe(
    '{"customer_id":"cust-1","items":[{"variant_id":"var-1","quantity":1}],"channel":"dashboard"}',
  );
  expect(sent[0].key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  expect(sent[0].headers["content-type"]).toBe("application/json");
  // The money terms are absent, not zero-filled.
  expect(sent[0].body).not.toContain("discount_total");
  expect(sent[0].body).not.toContain("shipping_total");
  expect(sent[0].body).not.toContain("tax_total");
});

test("typed money reaches the wire as strings beside the fields the server names", async ({ page }) => {
  const sent = await mockOrdersApi(page);
  await page.goto("/orders");
  await openDialogAndPickOne(page);
  await page.getByTestId("order-money-discount").fill("10");
  await page.getByTestId("order-money-shipping").fill("15");
  await page.getByTestId("order-money-tax").fill("5.5");
  await page.getByTestId("submit-order").click();
  await expect(page.getByText("Order created", { exact: true })).toBeVisible();

  expect(sent).toHaveLength(1);
  expect(JSON.parse(sent[0].body)).toEqual({
    customer_id: "cust-1",
    items: [{ variant_id: "var-1", quantity: 1 }],
    channel: "dashboard",
    discount_total: "10.00",
    shipping_total: "15.00",
    tax_total: "5.50",
  });
  // Money is never a JSON number on the way out.
  expect(sent[0].body).toContain('"tax_total":"5.50"');
});

test("a corrected retry after a 4xx reuses the dialog's key, as the guard's release rule allows", async ({ page }) => {
  // `idempotency.py` releases a key whose request failed with a 4xx — nothing
  // ran — so the SAME key may carry the fixed draft. The dialog keeps it.
  const sent = await mockOrdersApi(page, { onCreate: (attempt) => (attempt === 1 ? "reject" : "ok") });
  await page.goto("/orders");
  await openDialogAndPickOne(page);

  await page.getByTestId("order-money-tax").fill("7");
  await page.getByTestId("submit-order").click();
  await expect(page.getByText("the warehouse refused the reservation")).toBeVisible();
  // The dialog stays open WITH its draft — the write may or may not have landed.
  await expect(page.locator("#o-customer")).toHaveValue("cust-1");
  await expect(page.getByTestId("order-money-tax")).toHaveValue("7");

  await page.getByTestId("submit-order").click();
  await expect(page.getByText("Order created", { exact: true })).toBeVisible();

  expect(sent).toHaveLength(2);
  expect(sent[0].key).toBeTruthy();
  expect(sent[1].key).toBe(sent[0].key);
  expect(sent[1].body).toContain('"tax_total":"7.00"');
});

test("a 500 keeps the key too, and the guard's own terminal 409 then stops the dialog", async ({ page }) => {
  // First attempt: 5xx, outcome unknown, so the client must NOT re-key. Second
  // attempt under the same key: the server refuses (terminal-failed) and the
  // dialog reports that instead of minting a fresh key behind the merchant's
  // back — which would re-create the order the first attempt may have made.
  const sent = await mockOrdersApi(page, {
    onCreate: (attempt) => (attempt === 1 ? "server_error" : "poisoned"),
  });
  await page.goto("/orders");
  await openDialogAndPickOne(page);

  await page.getByTestId("submit-order").click();
  // exact: the diagnostics toast carries the same message plus the request
  // path ("upstream failure\nالمسار: /orders"), so a bare getByText matches
  // two elements and strict mode refuses.
  await expect(page.getByText("upstream failure", { exact: true })).toBeVisible();
  await expect(page.getByTestId("order-idempotency-conflict")).toHaveCount(0);

  await page.getByTestId("submit-order").click();
  const notice = page.getByTestId("order-idempotency-conflict");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("unknown outcome");
  expect(sent).toHaveLength(2);
  expect(sent[1].key).toBe(sent[0].key);
});

test("a replayed answer is reported as a replay, not as a second creation", async ({ page }) => {
  const sent = await mockOrdersApi(page, { onCreate: () => "replay" });
  await page.goto("/orders");
  await openDialogAndPickOne(page);
  await page.getByTestId("submit-order").click();

  await expect(page.getByText("Order already created", { exact: true })).toBeVisible();
  // The replay reason lives in the toast DESCRIPTION; Radix's hidden announcer
  // echoes title+description behind a "Notification " prefix, so a bare regex
  // resolves to two elements. Match the description element exactly (the mock
  // order number is deterministic).
  await expect(
    page.getByText("#ORD-1002 — The first response was replayed — the order was not created twice.", {
      exact: true,
    }),
  ).toBeVisible();
  expect(sent).toHaveLength(1);
});

test("a 409 stops the dialog: the key is kept and nothing is resent under a new one", async ({ page }) => {
  const sent = await mockOrdersApi(page, { onCreate: () => "conflict" });
  await page.goto("/orders");
  await openDialogAndPickOne(page);
  await page.getByTestId("submit-order").click();

  const notice = page.getByTestId("order-idempotency-conflict");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("No new order was created");
  await expect(notice).toContainText("Idempotency-Key reused with a different request body");
  await expect(notice).toContainText("will not be resent under a new key");
  // Blocked until a human looks at the orders list — a blind resend could
  // create the order twice, which is what the guard exists to prevent.
  await expect(page.getByTestId("submit-order")).toBeDisabled();
  await expect(page.locator("#o-customer")).toHaveValue("cust-1");
  expect(sent).toHaveLength(1);
});

test("closing after a 409 and reopening is a new intent with a new key", async ({ page }) => {
  const sent = await mockOrdersApi(page, { onCreate: (attempt) => (attempt === 1 ? "conflict" : "ok") });
  await page.goto("/orders");
  await openDialogAndPickOne(page);
  await page.getByTestId("submit-order").click();
  await expect(page.getByTestId("order-idempotency-conflict")).toBeVisible();

  await page.getByTestId("order-idempotency-conflict").getByRole("button", { name: "Close dialog" }).click();
  await expect(page.getByTestId("order-idempotency-conflict")).toHaveCount(0);

  await page.getByTestId("toggle-order-form").click();
  await expect(page.getByTestId("submit-order")).toBeEnabled();
  await page.getByTestId("submit-order").click();
  // exact: the a11y announcer echoes the same words with the order number
  // ("Notification Order created#ORD-…"), which a bare getByText also matches.
  await expect(page.getByText("Order created", { exact: true })).toBeVisible();

  expect(sent).toHaveLength(2);
  expect(sent[0].key).not.toBe(sent[1].key);
});
