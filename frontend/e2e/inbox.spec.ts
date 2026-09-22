import { expect, test } from "@playwright/test";
import { json, mockShell, seedAuth, serverError } from "./support";

/* W5 exit gate — inbox.
 *
 * Conversation rows carry `convo-<id>` / `unread-<id>` testids, so the list,
 * the unread badge and the channel badge can all be asserted without reading
 * Arabic copy. §99 adds the views rail (`view-<id>` chips), the assign action
 * (`assign-button` / `assign-to-me` / `unassign-button`) and the context
 * panel tabs (`ctx-tab-*`). */

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

/* §99 — views rail */

test("the views rail renders every §99 view and disables the unwired ones", async ({ page }) => {
  await page.route("**/api/v1/conversations**", (route) => json(route, CONVERSATIONS));

  await page.goto("/inbox");

  const rail = page.getByTestId("views-rail");
  await expect(rail).toBeVisible();
  // Backend-backed + client-filtered views are enabled.
  for (const id of ["my", "unassigned", "all", "sla-risk", "waiting-customer", "waiting-team", "ai"]) {
    await expect(rail.getByTestId(`view-${id}`)).toBeEnabled();
  }
  // No backend field/endpoint yet → rendered disabled, never faked.
  for (const id of ["priority", "vip", "ai-handover", "mentioned", "team", "custom"]) {
    await expect(rail.getByTestId(`view-${id}`)).toBeDisabled();
  }
});

test("clicking the unassigned view updates the URL and filters by assignee", async ({ page }) => {
  await page.route("**/api/v1/conversations**", (route) => json(route, CONVERSATIONS));

  await page.goto("/inbox");
  await page.getByTestId("view-unassigned").click();

  await expect(page).toHaveURL(/view=unassigned/);
  // Both fixtures are unassigned, so both rows stay visible.
  await expect(page.getByTestId("convo-c1")).toBeVisible();
  await expect(page.getByTestId("convo-c2")).toBeVisible();
});

test("the my view filters out conversations not assigned to the current user", async ({ page }) => {
  await page.route("**/api/v1/conversations**", (route) => json(route, CONVERSATIONS));

  await page.goto("/inbox?view=my");

  // mockShell's me id is `user-1`; no fixture is assigned to them.
  await expect(page.getByTestId("inbox-empty")).toBeVisible();
});

test("the waiting-customer view asks the server for that status", async ({ page }) => {
  await page.route("**/api/v1/conversations**", (route) => json(route, CONVERSATIONS));

  const statusReq = page.waitForRequest(
    (req) =>
      req.method() === "GET" &&
      req.url().includes("/api/v1/conversations") &&
      req.url().includes("status=waiting_customer"),
  );
  await page.goto("/inbox?view=waiting-customer");
  const request = await statusReq;
  expect(new URL(request.url()).searchParams.get("status")).toBe("waiting_customer");
});

test("a deep link with view and conversation opens the thread directly", async ({ page }) => {
  await page.route("**/api/v1/conversations**", (route) => json(route, CONVERSATIONS));
  await page.route("**/api/v1/conversations/c1/messages", (route) => json(route, MESSAGES));
  await page.route("**/api/v1/conversations/c1/read", (route) => route.fulfill({ status: 204 }));

  await page.goto("/inbox?view=unassigned&conversation=c1");

  await expect(page.getByTestId("reply-input")).toBeVisible();
  await expect(page.getByText("Do you have this in blue?")).toBeVisible();
  await expect(page.getByTestId("ctx-tab-customer")).toBeVisible();
  await expect(page.getByTestId("ctx-tab-orders")).toBeVisible();
  await expect(page.getByTestId("ctx-tab-timeline")).toBeVisible();
  await expect(page.getByTestId("ctx-tab-notes")).toBeVisible();
  // No customer-scoped AI endpoint yet → the tab stays disabled.
  await expect(page.getByTestId("ctx-tab-ai")).toBeDisabled();
});

/* §99 — assign action */

test("assigning a conversation to me patches the row optimistically", async ({ page }) => {
  await page.route("**/api/v1/conversations**", (route) => json(route, CONVERSATIONS));
  await page.route("**/api/v1/conversations/c1/assign", (route) =>
    json(route, { id: "assign-1" }),
  );

  await page.goto("/inbox");
  await page.getByTestId("convo-c1").click();

  await page.getByTestId("assign-button").click();
  const assignPost = page.waitForRequest(
    (req) => req.url().includes("/conversations/c1/assign") && req.method() === "POST",
  );
  await page.getByTestId("assign-to-me").click();
  const request = await assignPost;
  expect(request.postDataJSON()).toEqual({ user_id: "user-1" });

  // The optimistic row patch flips the unassign option on without a refetch.
  await page.getByTestId("assign-button").click();
  await expect(page.getByTestId("unassign-button")).toBeEnabled();
});

test("unassigning clears the assignee", async ({ page }) => {
  const assigned = {
    ...CONVERSATIONS,
    items: CONVERSATIONS.items.map((c) =>
      c.id === "c1" ? { ...c, assignee_user_id: "user-1" } : c,
    ),
  };
  await page.route("**/api/v1/conversations**", (route) => json(route, assigned));
  await page.route("**/api/v1/conversations/c1/assign", (route) =>
    json(route, { id: "assign-2" }),
  );

  await page.goto("/inbox");
  await page.getByTestId("convo-c1").click();

  await page.getByTestId("assign-button").click();
  const unassignPost = page.waitForRequest(
    (req) => req.url().includes("/conversations/c1/assign") && req.method() === "POST",
  );
  await page.getByTestId("unassign-button").click();
  const request = await unassignPost;
  expect(request.postDataJSON()).toEqual({ user_id: null });

  await page.getByTestId("assign-button").click();
  await expect(page.getByTestId("unassign-button")).toBeDisabled();
});
