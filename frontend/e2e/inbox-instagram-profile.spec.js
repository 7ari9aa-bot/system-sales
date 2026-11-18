import { expect, test } from "@playwright/test";

// An Instagram chat starts as a bare number. The list must show who it is as soon as the
// backend learns it, ask exactly once per chat, and never invent a name.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const NOW = new Date().toISOString();
const PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAUEBAAAACwAAAAAAQABAAACAkQBADs=";

function rowFor(over = {}) {
  return { id: "c1", channel: "instagram", status: "open", customer_id: "cu1", customer_name: "17841400000000001", customer_phone: null, customer_handle: null, customer_avatar_url: null, unread_count: 0, last_message_at: NOW, last_message_preview: "hi", last_message_direction: "inbound", last_message_content_type: "text", ...over };
}

async function open(page, { first, second, refresh }) {
  const calls = { refresh: 0, inbox: 0 };
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const u = new URL(route.request().url());
    const send = (d, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(d) });
    const p = u.pathname.replace("/api/v1", "");
    if (p === "/auth/me") return send({ id: "u", email: "owner@shop.com", full_name: "Owner", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([{ provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" }]);
    if (p === "/inbox") { calls.inbox += 1; return send({ items: u.searchParams.get("archived") === "true" ? [] : [calls.refresh > 0 ? second : first], next_cursor: null }); }
    if (p.endsWith("/refresh-profile")) { calls.refresh += 1; return refresh(send, route); }
    if (p.startsWith("/social/")) return send({ items: [] });
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByRole("button", { name: "Instagram", exact: true }).click();
  await page.getByRole("tab", { name: /Direct messages|الرسائل الخاصة/ }).or(page.getByRole("button", { name: /Direct messages|الرسائل الخاصة/ })).first().click();
  return calls;
}

test("a bare number becomes the real name once the backend learns it, asking only once", async ({ page }) => {
  const calls = await open(page, {
    first: rowFor(),
    second: rowFor({ customer_name: "Sara Ahmed", customer_handle: "sara.a", customer_avatar_url: PIXEL }),
    refresh: (send) => send({ updated: true }),
  });
  await expect(page.getByText("Sara Ahmed").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("17841400000000001")).toHaveCount(0);
  await expect(page.locator(`img[src="${PIXEL}"]`).first()).toBeVisible();
  await page.waitForTimeout(800);
  expect(calls.refresh).toBe(1);
});

test("with no real name yet, the @handle is shown instead of the number", async ({ page }) => {
  await open(page, {
    first: rowFor({ customer_handle: "sara.a" }),
    second: rowFor({ customer_handle: "sara.a" }),
    refresh: (send) => send({ updated: false }),
  });
  await expect(page.getByText("@sara.a").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("17841400000000001")).toHaveCount(0);
});

test("a refusal is tried once, shows the number honestly, and does not loop", async ({ page }) => {
  const calls = await open(page, { first: rowFor(), second: rowFor(), refresh: (send) => send({ updated: false }) });
  await expect(page.getByText("17841400000000001").first()).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(1200);
  expect(calls.refresh).toBe(1);
  expect(calls.inbox).toBeLessThanOrEqual(2); // no reload storm: nothing was learned
});

test("a failing profile call never breaks the list", async ({ page }) => {
  await open(page, { first: rowFor(), second: rowFor(), refresh: (send) => send({ detail: "boom" }, 500) });
  await expect(page.getByText("17841400000000001").first()).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(800);
  await expect(page.getByText("17841400000000001").first()).toBeVisible(); // still there after the 500
  await page.getByText("17841400000000001").first().click(); // and still usable
});

test("a real name already known is never replaced and needs no call", async ({ page }) => {
  const calls = await open(page, {
    first: rowFor({ customer_name: "Omar", customer_avatar_url: PIXEL }),
    second: rowFor({ customer_name: "Omar", customer_avatar_url: PIXEL }),
    refresh: (send) => send({ updated: false }),
  });
  await expect(page.getByText("Omar").first()).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(600);
  expect(calls.refresh).toBe(0);
});
