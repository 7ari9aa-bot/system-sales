import { expect, test } from "@playwright/test";
import { json, mockShell, seedAuth, serverError } from "./support";

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
