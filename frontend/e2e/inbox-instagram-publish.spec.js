import { expect, test } from "@playwright/test";

// Publishing a post from the inbox: the rules are shown BEFORE anything is uploaded, the request
// carries the pictures in the order chosen, and a failure keeps the pictures and the caption.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const T0 = new Date(Date.now() - 3600e3).toISOString();
const POST = { id: "p1", caption: "new shoes", media_type: "IMAGE", media_url: "", like_count: 3, comments_count: 0, comments_enabled: true, posted_at: T0 };

// A real (tiny) JPEG: starts FF D8 FF, like any camera file.
const JPEG = (n) => ({ name: `pic${n}.jpg`, mimeType: "image/jpeg", buffer: Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.from(`picture-${n}`)]) });
const PNG = { name: "logo.png", mimeType: "image/png", buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]) };

async function open(page, { failFirst = false } = {}) {
  const sent = [];
  let failed = false;
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname.replace("/api/v1", "");
    const send = (d, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(d) });
    if (p === "/auth/me") return send({ id: "u", email: "owner@shop.com", full_name: "Owner", is_platform_admin: false, tenants: [{ id: "t", name: "T", role: "owner" }] });
    if (p === "/channels/status") return send([{ provider: "instagram", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "shop" }]);
    if (p === "/social/posts" && req.method() === "POST") {
      sent.push(req.postDataJSON());
      if (failFirst && !failed) { failed = true; return send({ detail: "Instagram said no" }, 502); }
      return send({ post_id: "new1" }, 201);
    }
    if (p === "/social/posts") return send({ items: [POST] });
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByRole("button", { name: "Instagram", exact: true }).click();
  await page.getByTestId("ig-new-post-button").click();
  await expect(page.getByTestId("ig-new-post")).toBeVisible({ timeout: 15_000 });
  return sent;
}

test("Share stays off until there is a valid picture", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("ig-share")).toBeDisabled();
  await page.getByTestId("ig-file-input").setInputFiles(JPEG(1));
  await expect(page.getByTestId("ig-share")).toBeEnabled();
});

test("a PNG is refused with the reason, and nothing is uploaded", async ({ page }) => {
  const sent = await open(page);
  await page.getByTestId("ig-file-input").setInputFiles(PNG);
  await expect(page.getByTestId("ig-publish-error")).toContainText(/JPEG/);
  await expect(page.getByTestId("ig-share")).toBeDisabled();
  expect(sent).toHaveLength(0);
});

test("a caption over 2,200 characters is refused and counted", async ({ page }) => {
  await open(page);
  await page.getByTestId("ig-file-input").setInputFiles(JPEG(1));
  await page.getByTestId("ig-caption").fill("x".repeat(2201));
  await expect(page.getByTestId("ig-publish-error")).toContainText(/2,?200/);
  await expect(page.getByTestId("ig-share")).toBeDisabled();
});

test("a carousel is sent in the order chosen, after reordering", async ({ page }) => {
  const sent = await open(page);
  await page.getByTestId("ig-file-input").setInputFiles([JPEG(1), JPEG(2), JPEG(3)]);
  await expect(page.getByTestId("ig-picture-list").locator("li")).toHaveCount(3);
  await page.getByRole("button", { name: /Move later|تأخير/ }).first().click(); // picture 1 moves behind 2
  await page.getByTestId("ig-caption").fill("summer set");
  await page.getByTestId("ig-share").click();
  await expect(page.getByTestId("ig-new-post")).toHaveCount(0, { timeout: 10_000 });
  expect(sent).toHaveLength(1);
  const decoded = sent[0].pictures.map((b) => Buffer.from(b, "base64").toString("latin1").slice(4));
  expect(decoded).toEqual(["picture-2", "picture-1", "picture-3"]);
  expect(sent[0].caption).toBe("summer set");
});

test("a failed publish keeps the pictures and the caption, and a retry works", async ({ page }) => {
  const sent = await open(page, { failFirst: true });
  await page.getByTestId("ig-file-input").setInputFiles([JPEG(1), JPEG(2)]);
  await page.getByTestId("ig-caption").fill("keep me");
  await page.getByTestId("ig-share").click();
  await expect(page.getByTestId("ig-publish-error")).toContainText(/Instagram said no/);
  await expect(page.getByTestId("ig-picture-list").locator("li")).toHaveCount(2);
  await expect(page.getByTestId("ig-caption")).toHaveValue("keep me");
  await page.getByTestId("ig-share").click();
  await expect(page.getByTestId("ig-new-post")).toHaveCount(0, { timeout: 10_000 });
  expect(sent).toHaveLength(2);
});

test("the dialog stays inside the window on a phone", async ({ page }) => {
  await open(page);
  await page.setViewportSize({ width: 375, height: 640 });
  await page.getByTestId("ig-file-input").setInputFiles([JPEG(1), JPEG(2), JPEG(3), JPEG(4)]);
  const box = await page.getByTestId("ig-new-post").boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(376);
  expect(box.y + box.height).toBeLessThanOrEqual(641);
});
