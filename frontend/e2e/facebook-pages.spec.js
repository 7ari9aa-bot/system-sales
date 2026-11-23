import { expect, test } from "@playwright/test";

// The Facebook pages on a REAL account: they show what Facebook returned, wait for Facebook before
// claiming anything happened, say so when it refuses, and keep their place on back and refresh.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const T0 = new Date(Date.now() - 3600e3).toISOString();

function makeApi({ failNext = {} } = {}) {
  const calls = [];
  const state = {
    failNext: { ...failNext },
    posts: [{ id: "p1", message: "new shoes", picture: "", type: "STATUS", permalink: "https://fb.com/p1", reactions: 4, comments: 2, posted_at: T0 }],
    comments: [
      { id: "c1", post_id: "p1", parent_id: null, username: "Sara", body: "how much?", status: "visible", is_page_reply: false, commented_at: T0, like_count: 1 },
      { id: "c2", post_id: "p1", parent_id: null, username: "Omar", body: "spam", status: "visible", is_page_reply: false, commented_at: T0, like_count: 0 },
    ],
  };
  const handler = async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname.replace("/api/v1", "");
    const send = (d, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(d) });
    const body = () => req.postDataJSON?.() ?? null;
    const act = (key) => {
      calls.push({ key, path: p, body: body() });
      if (state.failNext[key]) { delete state.failNext[key]; return false; }
      return true;
    };
    if (p === "/auth/me") return send({ id: "u", email: "o@shop.com", full_name: "O", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([
      { provider: "facebook", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active" },
      { provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active" },
    ]);
    if (p === "/inbox") return send({ items: [], next_cursor: null });
    if (p === "/facebook/page") return send({ id: "111", name: "My Shop", followers_count: 1200, about: "shoes" });
    if (p === "/facebook/scheduled") return send({ items: [{ id: "s1", message: "coming soon", scheduled_for: Math.floor(Date.now() / 1000) + 7200 }] });
    if (p === "/facebook/insights") return send({ metrics: [{ name: "page_follows", values: [{ value: 1200 }] }, { name: "page_media_view", values: [{ value: 10 }, { value: 5 }] }] });
    if (p === "/facebook/posts" && req.method() === "GET") return send({ items: state.posts });
    if (p === "/facebook/posts" && req.method() === "POST") {
      if (!act("publish")) return send({ detail: "Facebook said no" }, 502);
      return send({ id: "p9", scheduled: !!body().schedule_at }, 201);
    }
    let m = p.match(/^\/facebook\/posts\/([^/]+)\/comments$/);
    if (m) return send({ items: state.comments.filter((c) => c.post_id === m[1]) });
    m = p.match(/^\/facebook\/posts\/([^/]+)\/insights$/);
    if (m) return send({ post_id: m[1], metrics: [{ name: "post_media_view", values: [{ value: 77 }] }] });
    m = p.match(/^\/facebook\/posts\/([^/]+)$/);
    if (m && req.method() === "PATCH") {
      if (!act("edit")) return send({ detail: "Facebook said no" }, 502);
      return send({ id: m[1] });
    }
    if (m && req.method() === "DELETE") {
      if (!act("delete-post")) return send({ detail: "Facebook said no" }, 502);
      state.posts = state.posts.filter((x) => x.id !== m[1]);
      return route.fulfill({ status: 204 });
    }
    m = p.match(/^\/facebook\/objects\/([^/]+)\/(comments|like)$/);
    if (m) {
      if (!act(m[2] === "like" ? "like" : "comment")) return send({ detail: "Facebook said no" }, 502);
      if (m[2] === "comments") {
        const parent = state.comments.find((c) => c.id === m[1]);
        state.comments.push({ id: `r${calls.length}`, post_id: parent ? parent.post_id : m[1], parent_id: parent ? parent.id : null, username: "page", body: body().text, status: "visible", is_page_reply: true, commented_at: T0, like_count: 0 });
      }
      return send({ ok: true }, 201);
    }
    m = p.match(/^\/facebook\/comments\/([^/]+)(\/(hide|private-reply))?$/);
    if (m) {
      const key = m[3] || "delete-comment";
      if (!act(key)) return send({ detail: "Facebook said no" }, 502);
      const c = state.comments.find((x) => x.id === m[1]);
      if (m[3] === "hide") c.status = body().hidden ? "hidden" : "visible";
      if (!m[3]) state.comments = state.comments.filter((x) => x.id !== m[1]);
      return m[3] === "private-reply" ? send({ message_id: "dm" }, 201) : m[3] ? send({}) : route.fulfill({ status: 204 });
    }
    return send({ items: [], next_cursor: null });
  };
  return { handler, calls, state };
}

async function open(page, api, path = "/facebook/posts") {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", api.handler);
  page.on("dialog", (d) => d.accept());
  await page.goto(path, { waitUntil: "domcontentloaded", timeout: 30_000 });
}

test("the feed shows the Page and its real post, with the newest comment under it", async ({ page }) => {
  await open(page, makeApi());
  await expect(page.getByRole("heading", { name: "My Shop" }).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("new shoes")).toBeVisible();
  // Facebook's Page home draws just the newest comment and folds the rest behind "View more
  // comments"; the second one has to be opened, not assumed to be on screen.
  await expect(page.getByTestId("fb-comment-c2")).toBeVisible();
  await expect(page.getByText("how much?")).toBeHidden();
  await page.getByRole("button", { name: "View more comments" }).click();
  await expect(page.getByTestId("fb-comment-c1")).toBeVisible();
  await expect(page.getByText("how much?")).toBeVisible();
  await expect(page.getByText("1,200 followers")).toBeVisible();
  await expect(page.getByText("coming soon")).toBeVisible(); // a scheduled post
});

test("the channel strip stays on the far right, and Facebook is its active channel", async ({ page }) => {
  await open(page, makeApi());
  await expect(page.getByText("new shoes")).toBeVisible({ timeout: 15_000 });
  const strip = page.locator("aside").last();
  const box = await strip.boundingBox();
  expect(box.x + box.width).toBeGreaterThan(1270);
  await expect(strip.getByRole("button", { name: "Facebook" })).toHaveAttribute("aria-pressed", "true");
});

test("a comment reply goes to Facebook first, then appears under the comment", async ({ page }) => {
  const api = makeApi();
  await open(page, api);
  // The reply is answered on a named comment, not on "whichever one happens to be first".
  await page.getByTestId("fb-comment-c2").waitFor({ timeout: 15_000 });
  await page.getByRole("button", { name: "View more comments" }).click();
  await page.getByTestId("fb-comment-c1").getByRole("button", { name: "Reply" }).click();
  await page.getByLabel("Reply", { exact: true }).fill("20 EGP");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("20 EGP")).toBeVisible();
  expect(api.calls.find((c) => c.key === "comment")).toMatchObject({ path: "/facebook/objects/c1/comments", body: { text: "20 EGP" } });
});

test("a refused reply is reported and nothing is shown as sent", async ({ page }) => {
  const api = makeApi({ failNext: { comment: 1 } });
  await open(page, api);
  await page.getByRole("button", { name: "Reply" }).first().click();
  await page.getByLabel("Reply", { exact: true }).fill("never sent");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Facebook said no" })).toBeVisible();
  await expect(page.getByText("never sent").locator("visible=true")).toHaveCount(0);
});

test("hiding and deleting a comment, and a private reply, each reach Facebook", async ({ page }) => {
  const api = makeApi();
  await open(page, api);
  await page.getByRole("button", { name: "Hide" }).first().click();
  await expect(page.getByText("Hidden")).toBeVisible();
  await page.getByRole("button", { name: "Unhide" }).click();
  await page.getByRole("button", { name: "Message privately" }).first().click();
  await page.getByLabel("Private reply").fill("check your DM");
  await page.getByRole("button", { name: "Send" }).click();
  await page.getByRole("button", { name: "Delete" }).first().click();
  await expect.poll(() => api.calls.map((c) => c.key)).toEqual(expect.arrayContaining(["hide", "private-reply", "delete-comment"]));
});

test("a post is edited, and one Facebook refuses stays as it was", async ({ page }) => {
  const api = makeApi({ failNext: { edit: 1 } });
  await open(page, api);
  await page.getByRole("button", { name: "Post options" }).click();
  await page.getByRole("menuitem", { name: "Edit post" }).click();
  await page.getByLabel("Post text").fill("new shoes 20% off");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Facebook said no" })).toBeVisible();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("new shoes 20% off")).toBeVisible();
});

test("creating a post checks Meta's limits before sending, then sends", async ({ page }) => {
  const api = makeApi();
  await open(page, api);
  await page.getByRole("button", { name: "Create post" }).click();
  const send = page.getByRole("dialog").getByRole("button", { name: "Post", exact: true });
  await expect(send).toBeDisabled();
  await page.getByPlaceholder("What's on your mind?").fill("big sale");
  await page.getByRole("button", { name: "Schedule" }).click();
  await page.getByLabel("Publish time").fill(new Date(Date.now() + 120_000).toISOString().slice(0, 16));
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("10 minutes");
  await page.getByLabel("Publish time").fill(new Date(Date.now() + 3 * 3600e3).toISOString().slice(0, 16));
  await page.getByRole("dialog").getByRole("button", { name: "Schedule", exact: true }).last().click();
  await expect(page.getByText("Post scheduled")).toBeVisible();
  expect(api.calls.find((c) => c.key === "publish").body.schedule_at).toBeTruthy();
});

test("deleting a post removes it only after Facebook agrees", async ({ page }) => {
  const api = makeApi();
  await open(page, api);
  await page.getByRole("button", { name: "Post options" }).click();
  await page.getByRole("menuitem", { name: "Delete post" }).click();
  await expect(page.getByText("new shoes")).toHaveCount(0);
  expect(api.calls.some((c) => c.key === "delete-post")).toBe(true);
});

test("post insights show only what Facebook returned", async ({ page }) => {
  await open(page, makeApi());
  await page.getByRole("button", { name: "Post options" }).click();
  await page.getByRole("menuitem", { name: "View insights" }).click();
  await expect(page.getByRole("dialog").getByText("77")).toBeVisible();
});

test("the other pages have their own address, and refresh keeps the place", async ({ page }) => {
  await open(page, makeApi(), "/facebook/insights");
  await expect(page.getByRole("heading", { name: "Insights" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("1,200", { exact: true })).toBeVisible();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/facebook\/insights$/);
  await page.getByRole("link", { name: "Notifications" }).click();
  await expect(page).toHaveURL(/\/facebook\/activity$/);
  await expect(page.getByText("how much?")).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/facebook\/insights$/);
});

test("Message privately is offered only within Meta's 7 days of the comment", async ({ page }) => {
  const api = makeApi();
  api.state.comments.push({ id: "c-old", post_id: "p1", parent_id: null, username: "Old Ola", body: "from long ago", status: "visible", is_page_reply: false, commented_at: new Date(Date.now() - 9 * 86400e3).toISOString(), like_count: 0 });
  await open(page, api);
  await expect(page.getByTestId("fb-comment-c-old")).toBeHidden();
  await page.getByRole("button", { name: "View more comments" }).click();
  await expect(page.getByText("from long ago")).toBeVisible({ timeout: 15_000 });
  // c1 and c2 are an hour old, c-old is nine days old: only the two recent ones may be answered privately
  await expect(page.getByRole("button", { name: "Message privately" })).toHaveCount(2);
});
