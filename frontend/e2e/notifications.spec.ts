import { expect, test } from "@playwright/test";
import { json, mockShell, seedAuth, serverError } from "./support";

/* Notifications centre — extra coverage beyond the named W5 gate areas.
 *
 * The filter chips and the bulk action already carry testids, so the queue can
 * be driven without depending on translated copy. */

const LIST = [
  {
    id: "n1",
    kind: "new_message",
    title: "New message from Layla",
    body: "Do you have this in blue?",
    action_url: "/inbox?conversation=c1",
    payload: {},
    read_at: null,
    created_at: "2026-09-20T10:00:00Z",
  },
  {
    id: "n2",
    kind: "order_update",
    title: "Order ORD-1001 paid",
    body: "Payment captured",
    action_url: "/orders",
    payload: {},
    read_at: "2026-09-20T09:00:00Z",
    created_at: "2026-09-20T09:00:00Z",
  },
];

const SUMMARY = {
  total: 2,
  unread: 1,
  by_kind: [
    { kind: "new_message", total: 1, unread: 1 },
    { kind: "order_update", total: 1, unread: 0 },
  ],
};

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await mockShell(page);
  await page.route("**/api/v1/notifications**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/summary")) return json(route, SUMMARY);
    if (path.endsWith("/unread-count")) return json(route, { count: 1 });
    return json(route, LIST);
  });
});

test("renders the list and the unread filter narrows the queue", async ({ page }) => {
  await page.goto("/notifications");

  await expect(page.getByTestId("notif-n1")).toBeVisible();
  await expect(page.getByTestId("notif-n2")).toBeVisible();
  await expect(page.getByTestId("notif-filter-all")).toContainText("2");
  await expect(page.getByTestId("notif-filter-unread")).toContainText("1");

  await page.getByTestId("notif-filter-unread").click();
  await expect(page.getByTestId("notif-filter-unread")).toHaveAttribute("aria-pressed", "true");
});

test("marking all as read posts to the API", async ({ page }) => {
  await page.goto("/notifications");

  const posted = page.waitForRequest(
    (request) =>
      request.url().includes("/api/v1/notifications/mark-all-read") && request.method() === "POST",
  );
  await page.getByTestId("notifications-mark-all").click();
  await posted;
});

test("a failed notifications request renders a retryable alert", async ({ page }) => {
  await page.route("**/api/v1/notifications**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/summary")) return json(route, SUMMARY);
    if (path.endsWith("/unread-count")) return json(route, { count: 1 });
    return serverError(route, "notifications unavailable");
  });

  await page.goto("/notifications");

  const alert = page.getByTestId("error-state");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("notifications unavailable");
  await expect(alert.getByRole("button")).toBeVisible();
});
