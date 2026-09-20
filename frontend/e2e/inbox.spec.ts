import { expect, test } from "@playwright/test";
import { json, mockShell, seedAuth, serverError } from "./support";

/* W5 exit gate — inbox.
 *
 * Conversation rows carry `convo-<id>` / `unread-<id>` testids, so the list,
 * the unread badge and the channel badge can all be asserted without reading
 * Arabic copy. */

const CONVERSATIONS = {
  items: [
    {
      id: "c1",
      customer_id: "cust-1",
      customer_name: "Layla H.",
      customer_phone: "+201000000001",
      channel: "whatsapp",
      status: "open",
      unread_count: 2,
      assignee_user_id: null,
      last_message_at: "2026-09-20T10:00:00Z",
    },
    {
      id: "c2",
      customer_id: "cust-2",
      customer_name: "Omar S.",
      customer_phone: null,
      channel: "telegram",
      status: "open",
      unread_count: 0,
      assignee_user_id: null,
      last_message_at: null,
    },
  ],
  next_cursor: null,
};

const MESSAGES = {
  items: [
    {
      id: "m1",
      direction: "inbound",
      sender_type: "customer",
      body: "Do you have this in blue?",
      media_url: null,
      media_type: null,
      status: "delivered",
      created_at: "2026-09-20T10:00:00Z",
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await mockShell(page);
});

test("lists conversations with unread and channel badges", async ({ page }) => {
  await page.route("**/api/v1/conversations**", (route) => json(route, CONVERSATIONS));

  await page.goto("/inbox");

  await expect(page.getByTestId("convo-c1")).toBeVisible();
  await expect(page.getByTestId("convo-c2")).toBeVisible();
  await expect(page.getByTestId("unread-c1")).toHaveText("2");
  await expect(page.getByTestId("convo-c1").getByText("whatsapp")).toBeVisible();
  await expect(page.getByTestId("convo-c2").getByText("telegram")).toBeVisible();
});

test("selecting a conversation opens its thread and the reply box", async ({ page }) => {
  await page.route("**/api/v1/conversations**", (route) => json(route, CONVERSATIONS));
  await page.route("**/api/v1/conversations/c1/messages", (route) => json(route, MESSAGES));
  await page.route("**/api/v1/conversations/c1/read", (route) => route.fulfill({ status: 204 }));

  await page.goto("/inbox");
  await page.getByTestId("convo-c1").click();

  await expect(page.getByTestId("reply-input")).toBeVisible();
  await expect(page.getByText("Do you have this in blue?")).toBeVisible();
});

test("an empty inbox renders the empty state", async ({ page }) => {
  await page.route("**/api/v1/conversations**", (route) =>
    json(route, { items: [], next_cursor: null }),
  );

  await page.goto("/inbox");

  await expect(page.getByTestId("inbox-empty")).toBeVisible();
  await expect(page.getByTestId("convo-c1")).toHaveCount(0);
});

test("a failed conversations request renders a retryable alert", async ({ page }) => {
  await page.route("**/api/v1/conversations**", (route) => serverError(route, "inbox unavailable"));

  await page.goto("/inbox");

  const alert = page.getByTestId("error-state");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("inbox unavailable");
  await expect(alert.getByRole("button")).toBeVisible();
});
