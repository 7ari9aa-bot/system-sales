import { expect, test } from "@playwright/test";

// UI contract over mocked HTTP: the WhatsApp chat list (tabs, search, pin, mute,
// archive, mark unread). The "server" below keeps the state, as the real one does.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";

function makeRows() {
  const at = (h) => `2026-11-17T${String(h).padStart(2, "0")}:00:00+00:00`;
  const r = (id, name, over = {}) => ({
    id, channel: "whatsapp", status: "open", customer_id: `cust-${id}`, customer_name: name,
    customer_phone: `+2010000000${id}`, unread_count: 0, assignee_user_id: null,
    last_message_at: at(9), last_message_preview: `hello ${name}`, last_message_content_type: "text",
    last_message_direction: "inbound", last_message_status: "received",
    pinned_at: null, muted_until: null, archived_at: null, marked_unread: false, ...over,
  });
  return [
    r("1", "أحمد علي", { unread_count: 3, last_message_at: at(10) }),
    r("2", "Sara", { last_message_at: at(9), last_message_direction: "outbound", last_message_status: "read" }),
    r("3", "Omar", { last_message_at: at(8) }),
    r("4", "Old Chat", { archived_at: "2026-11-01T00:00:00+00:00", last_message_at: at(1) }),
  ];
}

async function boot(page) {
  const rows = makeRows();
  const calls = [];
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const send = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (url.pathname === "/api/v1/auth/me") {
      return send({ id: "u", email: "m@example.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    }
    const state = url.pathname.match(/\/conversations\/([^/]+)\/list-state$/);
    if (state && req.method() === "POST") {
      const body = req.postDataJSON();
      calls.push(body);
      const row = rows.find((x) => x.id === state[1]);
      const now = new Date().toISOString();
      if (body.pinned === true) { row.pinned_at = now; row.archived_at = null; }
      if (body.pinned === false) row.pinned_at = null;
      if (body.archived === true) { row.archived_at = now; row.pinned_at = null; }
      if (body.archived === false) row.archived_at = null;
      if (body.marked_unread !== undefined) row.marked_unread = body.marked_unread;
      if (body.mute === "always") row.muted_until = "9999-12-31T00:00:00+00:00";
      if (body.mute === "off") row.muted_until = null;
      return send({ id: row.id, pinned_at: row.pinned_at, muted_until: row.muted_until, archived_at: row.archived_at, marked_unread: row.marked_unread });
    }
    if (url.pathname === "/api/v1/inbox") {
      const archived = url.searchParams.get("archived") === "true";
      return send({ items: rows.filter((x) => Boolean(x.archived_at) === archived), next_cursor: null });
    }
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-list")).toBeVisible();
  return { rows, calls };
}

const rowsText = (page) => page.getByTestId("chat-row").allInnerTexts();
const rowFor = (page, name) => page.getByTestId("chat-row").filter({ hasText: name });

test("archived chats are hidden from the main list and live behind an Archived entry", async ({ page }) => {
  await boot(page);
  await expect(rowFor(page, "Old Chat")).toHaveCount(0);
  await expect(page.getByTestId("open-archive")).toContainText("1");
  await page.getByTestId("open-archive").click();
  await expect(rowFor(page, "Old Chat")).toBeVisible();
  await expect(rowFor(page, "Sara")).toHaveCount(0);
});

test("the Unread tab keeps only unread chats", async ({ page }) => {
  await boot(page);
  await page.getByTestId("tab-unread").click();
  await expect(page.getByTestId("chat-row")).toHaveCount(1);
  await expect(rowFor(page, "أحمد علي")).toBeVisible();
});

test("search ignores Arabic spelling variants", async ({ page }) => {
  await boot(page);
  await page.getByRole("textbox").first().fill("احمد");
  await expect(page.getByTestId("chat-row")).toHaveCount(1);
  await expect(rowFor(page, "أحمد علي")).toBeVisible();
});

test("pinning moves a chat to the top, after the server confirms", async ({ page }) => {
  const { calls } = await boot(page);
  const before = await rowsText(page);
  expect(before[0]).toContain("أحمد علي");
  await rowFor(page, "Omar").hover();
  await rowFor(page, "Omar").getByTestId("row-options").click();
  await page.getByTestId("act-pin").click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0]).toEqual({ pinned: true });
  await expect(page.getByTestId("chat-row").first()).toContainText("Omar");
  await expect(page.getByTestId("chat-row").first()).toHaveAttribute("data-pinned", "true");
});

test("archiving removes a chat from the list and shows it in the archive", async ({ page }) => {
  const { calls } = await boot(page);
  await rowFor(page, "Sara").getByTestId("row-options").click();
  await page.getByTestId("act-archive").click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0]).toEqual({ archived: true });
  await expect(rowFor(page, "Sara")).toHaveCount(0);
  await expect(page.getByTestId("open-archive")).toContainText("2");
});

test("muting always sends the closed value and greys the unread badge", async ({ page }) => {
  const { calls } = await boot(page);
  await rowFor(page, "أحمد علي").getByTestId("row-options").click();
  await page.getByTestId("act-mute").click();
  await page.getByTestId("mute-always").click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0]).toEqual({ mute: "always" });
  const badge = rowFor(page, "أحمد علي").getByTestId("unread-badge");
  await expect(badge).toHaveClass(/wa-text-faint/);
  await expect(badge).toHaveCSS("background-color", "rgb(134, 150, 160)");
});

test("marking a read chat unread shows a dot, with no number", async ({ page }) => {
  const { calls } = await boot(page);
  await rowFor(page, "Sara").getByTestId("row-options").click();
  await page.getByTestId("act-unread").click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0]).toEqual({ marked_unread: true });
  const badge = rowFor(page, "Sara").getByTestId("unread-badge");
  await expect(badge).toBeVisible();
  await expect(badge).toHaveText("");
});

test("a chat we answered shows its delivery tick before the preview", async ({ page }) => {
  await boot(page);
  await expect(rowFor(page, "Sara").locator('[data-status="read"]')).toBeVisible();
  await expect(rowFor(page, "Omar").locator("[data-status]")).toHaveCount(0);
});

test("the options menu closes with Escape", async ({ page }) => {
  await boot(page);
  await rowFor(page, "Sara").getByTestId("row-options").click();
  await expect(page.getByTestId("chat-list-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("chat-list-menu")).toHaveCount(0);
});
