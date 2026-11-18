import { expect, test } from "@playwright/test";

// Comments in the post view on a REAL account: it must show what the platform returned, wait for the platform
// before claiming anything was sent, and say so out loud when something fails.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const T0 = new Date(Date.now() - 3600e3).toISOString();
const OLD = new Date(Date.now() - 9 * 24 * 3600e3).toISOString();

function makeApi({ posts, comments, failNext = {} }) {
  const calls = [];
  const state = { comments: structuredClone(comments), failNext: { ...failNext } };
  const handler = async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    const send = (d, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(d) });
    const p = u.pathname.replace("/api/v1", "");
    if (p === "/auth/me") return send({ id: "u", email: "owner@shop.com", full_name: "Owner", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([{ provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" }]);
    if (p === "/inbox") return send({ items: [], next_cursor: null });
    if (p === "/social/posts") return send({ items: posts });
    let m = p.match(/^\/social\/posts\/([^/]+)\/comments$/);
    if (m) return send({ items: state.comments.filter((c) => c.post_id === m[1]) });
    m = p.match(/^\/social\/comments\/([^/]+)(\/(reply|hide|private-reply))?$/);
    if (m) {
      const [, id, , action] = m;
      const key = action || "delete";
      calls.push({ key, id, body: req.postDataJSON?.() ?? null });
      if (state.failNext[key]) { delete state.failNext[key]; return send({ detail: "Instagram said no" }, 502); }
      const c = state.comments.find((x) => x.id === id);
      if (action === "hide") c.status = req.postDataJSON().hidden ? "hidden" : "visible";
      if (action === "private-reply") c.private_replied_at = T0;
      if (action === "reply") state.comments.push({ id: `r-${calls.length}`, post_id: c.post_id, parent_id: c.parent_id || c.id, username: "shop", body: req.postDataJSON().text, status: "visible", is_page_reply: true, commented_at: T0, like_count: 0 });
      if (!action) state.comments = state.comments.filter((x) => x.id !== id);
      return action === "private-reply" ? send({ message_id: "dm1" }, 201) : action ? send({}, 200) : route.fulfill({ status: 204 });
    }
    return send({ items: [], next_cursor: null });
  };
  return { handler, calls, state };
}

const POST = { id: "p1", caption: "new shoes", media_type: "IMAGE", media_url: "", like_count: 3, comments_count: 2, comments_enabled: true, posted_at: T0 };
const C1 = { id: "c1", post_id: "p1", parent_id: null, username: "sara", body: "how much?", status: "visible", is_page_reply: false, commented_at: T0, like_count: 1 };
const C2 = { id: "c2", post_id: "p1", parent_id: null, username: "omar", body: "too late", status: "visible", is_page_reply: false, commented_at: OLD, like_count: 0 };

const menu = async (page, n = 0) => { await page.getByRole("button", { name: /Comment options|خيارات التعليق/ }).nth(n).click(); };

async function open(page, api) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", api.handler);
  await page.goto("/instagram/p/p1", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("ig-comment").first()).toBeVisible({ timeout: 15_000 });
}

test("a real account sees its real comments, not the demo data", async ({ page }) => {
  const api = makeApi({ posts: [POST], comments: [C1, C2] });
  await open(page, api);
  await expect(page.getByText("how much?")).toBeVisible();
  await expect(page.getByText("new shoes").first()).toBeVisible();
  await expect(page.getByText(/Demo data|بيانات تجريبية/)).toHaveCount(0);
});

test("a reply that fails keeps what was typed and says so", async ({ page }) => {
  const api = makeApi({ posts: [POST], comments: [C1], failNext: { reply: true } });
  await open(page, api);
  await page.getByRole("button", { name: /^(Reply|رد)$/ }).first().click();
  const box = page.locator("#instagram-comment-reply");
  await box.fill("we have it in 42");
  await box.press("Enter");
  await expect(page.getByTestId("ig-action-error")).toContainText("Instagram said no");
  await expect(box).toHaveValue("we have it in 42");
  await expect(page.getByText("we have it in 42")).toHaveCount(1); // only in the box, never in the thread
  await box.press("Enter"); // the retry goes through
  await expect(page.getByTestId("ig-action-error")).toHaveCount(0);
  await expect(page.getByText("we have it in 42")).toHaveCount(1);
  await expect(page.getByTestId("ig-comment")).toHaveCount(2);
  expect(api.calls.filter((c) => c.key === "reply")).toHaveLength(2);
});

test("hiding marks the comment and can be undone", async ({ page }) => {
  const api = makeApi({ posts: [POST], comments: [C1] });
  await open(page, api);
  await menu(page);
  await page.getByTestId("ig-hide").click();
  await expect(page.getByTestId("ig-hidden-badge")).toBeVisible();
  await expect(page.getByTestId("ig-comment").first()).toHaveAttribute("data-hidden", "true");
  await menu(page);
  await page.getByTestId("ig-hide").click();
  await expect(page.getByTestId("ig-hidden-badge")).toHaveCount(0);
  expect(api.calls.map((c) => c.body.hidden)).toEqual([true, false]);
});

test("deleting asks first, and removes the comment only after Instagram agreed", async ({ page }) => {
  const api = makeApi({ posts: [POST], comments: [C1] });
  await open(page, api);
  page.once("dialog", (d) => d.dismiss());
  await menu(page);
  await page.getByTestId("ig-delete").click();
  expect(api.calls).toHaveLength(0);
  page.once("dialog", (d) => d.accept());
  await menu(page);
  await page.getByTestId("ig-delete").click();
  await expect(page.getByText("how much?")).toHaveCount(0);
  expect(api.calls).toEqual([{ key: "delete", id: "c1", body: null }]);
});

test("a private reply is one-shot and blocked after 7 days", async ({ page }) => {
  const api = makeApi({ posts: [POST], comments: [C1, C2] });
  await open(page, api);
  const buttons = page.getByTestId("ig-private-reply");
  await menu(page, 0);
  await menu(page, 1);
  await expect(buttons.nth(1)).toBeDisabled(); // the 9-day-old comment
  await buttons.nth(0).click();
  await expect(page.getByTestId("ig-private-banner")).toContainText("sara");
  const box = page.locator("#instagram-comment-reply");
  await box.fill("price is 50");
  await box.press("Enter");
  await expect(page.getByTestId("ig-private-banner")).toHaveCount(0);
  await expect(buttons.nth(0)).toBeDisabled(); // already used its one reply
  expect(api.calls).toEqual([{ key: "private-reply", id: "c1", body: { text: "price is 50" } }]);
});

test("an account with no posts is told how to fix it, not shown a blank page", async ({ page }) => {
  const api = makeApi({ posts: [], comments: [] });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", api.handler);
  await page.goto("/instagram/profile", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("ig-empty")).toContainText(/reconnect|أعد ربط/);
});
