import { expect, test } from "@playwright/test";
import { json, mockShell, seedAuth, seedLang, serverError } from "./support";

/* W5 exit gate — orders. */

const ORDERS = {
  items: [
    {
      id: "o1",
      number: "ORD-1001",
      customer_id: "cust-1",
      status: "delivered",
      grand_total: "250.00",
      currency: "EGP",
      placed_at: "2026-09-19T09:00:00Z",
      created_at: "2026-09-19T09:00:00Z",
    },
  ],
};

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

const PRODUCTS = [
  {
    id: "prod-1",
    title: "Coffee Beans",
    slug: "coffee-beans",
    status: "active",
    variants: [{ id: "var-1", title: "250g", sku: "CB-250", price: "120.00" }],
  },
];

const CREATED_ORDER = {
  id: "o-new",
  number: "ORD-1002",
  status: "pending",
  grand_total: "120.00",
  currency: "EGP",
};

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await mockShell(page);
  await page.route("**/api/v1/products**", (route) => json(route, []));
  await page.route("**/api/v1/customers**", (route) => json(route, CUSTOMERS));
});

test("renders the orders table with the resolved customer name", async ({ page }) => {
  await page.route("**/api/v1/orders**", (route) => json(route, ORDERS));

  await page.goto("/orders");

  await expect(page.getByTestId("orders-table")).toBeVisible();
  await expect(page.getByText("ORD-1001")).toBeVisible();
  await expect(page.getByText("Layla H.")).toBeVisible();
  await expect(page.getByText("delivered")).toBeVisible();
});

test("an empty order list renders the empty state", async ({ page }) => {
  await page.route("**/api/v1/orders**", (route) => json(route, { items: [], next_cursor: null }));

  await page.goto("/orders");

  await expect(page.getByTestId("orders-empty")).toBeVisible();
});

test("the create-order dialog opens from the page header", async ({ page }) => {
  await page.route("**/api/v1/orders**", (route) => json(route, ORDERS));

  await page.goto("/orders");
  await page.getByTestId("toggle-order-form").click();

  await expect(page.getByTestId("submit-order")).toBeVisible();
});

test("a failed orders request renders a retryable alert", async ({ page }) => {
  await page.route("**/api/v1/orders**", (route) => serverError(route, "orders unavailable"));

  await page.goto("/orders");

  const alert = page.getByTestId("error-state");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("orders unavailable");
  await expect(alert.getByRole("button")).toBeVisible();
});

/* W0.2 — the create toast's Undo must hit the real cancel route, keyed by
 * order id (not number), through the shared API client. */

async function createOrderFromDialog(page: import("@playwright/test").Page) {
  await page.goto("/orders");
  await page.getByTestId("toggle-order-form").click();
  await page.locator("#o-customer").selectOption("cust-1");
  await page.getByLabel("Products 1").selectOption("var-1");
  await page.getByTestId("submit-order").click();
}

test("undo on the create toast cancels the order via POST /orders/{id}/cancel", async ({ page }) => {
  await seedLang(page, "en");
  await page.route("**/api/v1/products**", (route) => json(route, PRODUCTS));
  await page.route("**/api/v1/orders**", (route) =>
    route.request().method() === "POST" ? json(route, CREATED_ORDER, 201) : json(route, ORDERS),
  );
  const cancelPaths: string[] = [];
  await page.route("**/api/v1/orders/*/cancel", (route) => {
    cancelPaths.push(new URL(route.request().url()).pathname);
    return json(route, { ok: true });
  });

  await createOrderFromDialog(page);
  await page.getByRole("button", { name: "Undo" }).click();

  // exact: Radix's aria live region also carries "Notification Order cancelled".
  await expect(page.getByText("Order cancelled", { exact: true })).toBeVisible();
  // Keyed by the order id, never the human-facing number ORD-1002.
  expect(cancelPaths).toEqual(["/api/v1/orders/o-new/cancel"]);
});

test("a failed cancel surfaces the API error in a danger toast", async ({ page }) => {
  await seedLang(page, "en");
  await page.route("**/api/v1/products**", (route) => json(route, PRODUCTS));
  await page.route("**/api/v1/orders**", (route) =>
    route.request().method() === "POST" ? json(route, CREATED_ORDER, 201) : json(route, ORDERS),
  );
  await page.route("**/api/v1/orders/*/cancel", (route) => serverError(route, "cannot cancel"));

  await createOrderFromDialog(page);
  await page.getByRole("button", { name: "Undo" }).click();

  // exact: skip the aria live-region clone ("Notification Undo failed …").
  const danger = page.getByText("Undo failed", { exact: true });
  await expect(danger).toBeVisible();
  await expect(page.getByText("cannot cancel", { exact: true })).toBeVisible();
});
