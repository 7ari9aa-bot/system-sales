import { expect, test } from "@playwright/test";

// UI contract tests over mocked HTTP: they prove what the account menu shows and
// does in the browser. They are not evidence about backend persistence.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function setup(page, { lang = "en", user = {}, avatarUrl = null, avatarStatus = 200 } = {}) {
  const session = { user: { ...user }, avatarUrl, avatarStatus, avatarUploads: [], logouts: 0 };
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.addInitScript((locale) => localStorage.setItem("salesos.lang", locale), lang);
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const send = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path === "/api/v1/auth/me") {
      return send({
        id: session.user.id ?? "user-1",
        email: session.user.email ?? "merchant@example.com",
        full_name: session.user.full_name ?? "Hamed Adel",
        is_platform_admin: false,
        avatar_url: session.avatarUrl,
        tenants: [{ id: "tenant", name: "Shop", slug: "shop", role_code: "owner" }],
      });
    }
    if (path === "/api/v1/users/me/avatar") {
      session.avatarUploads.push({
        method: route.request().method(),
        contentType: route.request().headers()["content-type"] ?? null,
      });
      if (session.avatarStatus !== 200) return send({ error: { code: "validation_error", message: "internal storage detail" } }, session.avatarStatus);
      if (route.request().method() === "DELETE") session.avatarUrl = null;
      else session.avatarUrl = `${ORIGIN}/api/v1/media/avatar.png`;
      return send({ id: session.user.id ?? "user-1", avatar_url: session.avatarUrl });
    }
    if (path === "/api/v1/auth/logout") { session.logouts += 1; return send({ ok: true }); }
    if (path === "/api/v1/media/avatar.png") return route.fulfill({ status: 200, contentType: "image/png", body: png });
    return send({});
  });
  return session;
}

async function openMenu(page) {
  await page.goto("/dashboard");
  const trigger = page.getByRole("button", { name: /Account menu|قائمة الحساب/ });
  await expect(trigger).toBeVisible();
  await trigger.click();
  return page.getByRole("menu").first();
}

test("the account menu holds only what this product really has", async ({ page }, testInfo) => {
  await setup(page);
  const menu = await openMenu(page);
  await expect(menu.getByText("Hamed Adel")).toBeVisible();
  await expect(menu.getByText("merchant@example.com")).toBeVisible();
  await expect(menu.getByRole("button", { name: /Settings|الإعدادات/ })).toBeVisible();
  await expect(menu.getByRole("group", { name: /Theme|المظهر/ })).toBeVisible();
  await expect(menu.getByRole("group", { name: /language|اللغة/i })).toBeVisible();

  // Nothing invented: no plan, no credits, no fake memory/feedback/updater.
  for (const absent of ["Plan", "Credits", "Upgrade", "Buy", "Memory", "Feedback", "Updates", "144.64", "v2.4.0"]) {
    await expect(menu.getByText(absent, { exact: false })).toHaveCount(0);
  }
  await menu.screenshot({ path: testInfo.outputPath("account-menu-en.png") });
});

test("the menu is translated and a stored picture replaces the letters", async ({ page }, testInfo) => {
  await setup(page, {
    lang: "ar",
    avatarUrl: `${ORIGIN}/api/v1/media/avatar.png`,
    user: { full_name: "أحمد عادل", email: "ahmed@example.com" },
  });
  const menu = await openMenu(page);
  await expect(menu.getByText("أحمد عادل")).toBeVisible();
  await expect(menu.getByRole("button", { name: /الإعدادات/ })).toBeVisible();
  await expect(menu.getByRole("group", { name: /المظهر/ })).toBeVisible();
  await expect(menu.getByRole("group", { name: /لغة الواجهة|اللغة/ })).toBeVisible();
  await expect(menu.getByRole("button", { name: /إزالة/ })).toBeVisible();
  await expect(menu.locator("img")).toHaveCount(1);
  await menu.screenshot({ path: testInfo.outputPath("account-menu-ar.png") });
});

test("the avatar is the account's letters until a picture exists", async ({ page }) => {
  await setup(page);
  const menu = await openMenu(page);
  await expect(menu.locator('[aria-hidden="true"]').filter({ hasText: "HA" })).toBeVisible();
  await expect(menu.getByRole("button", { name: /Add profile picture|إضافة صورة شخصية/ })).toBeVisible();
  await expect(menu.locator("img")).toHaveCount(0);
});

test("uploading a picture sends the bytes and repaints the avatar", async ({ page }) => {
  const session = await setup(page);
  const menu = await openMenu(page);
  await menu.locator('input[type="file"]').setInputFiles({ name: "me.png", mimeType: "image/png", buffer: png });
  await expect(menu.getByText("Profile picture updated.")).toBeVisible();
  expect(session.avatarUploads).toHaveLength(1);
  expect(session.avatarUploads[0].method).toBe("PUT");
  expect(session.avatarUploads[0].contentType).toBe("image/png");
  await expect(menu.locator("img")).toHaveCount(1);
  await expect(menu.getByRole("button", { name: /Remove|إزالة/ })).toBeVisible();
});

test("a picture that is not one is refused before it leaves the browser", async ({ page }) => {
  const session = await setup(page);
  const menu = await openMenu(page);
  await menu.locator('input[type="file"]').setInputFiles({ name: "sticker.gif", mimeType: "image/gif", buffer: png });
  await expect(menu.getByRole("alert")).toContainText("PNG, JPEG or WebP");
  expect(session.avatarUploads).toEqual([]);
});

test("a refused write says it failed without echoing the server", async ({ page }) => {
  await setup(page, { avatarStatus: 400 });
  const menu = await openMenu(page);
  await menu.locator('input[type="file"]').setInputFiles({ name: "me.png", mimeType: "image/png", buffer: png });
  await expect(menu.getByRole("alert")).toContainText("not saved");
  await expect(menu).not.toContainText("internal storage detail");
  await expect(menu.locator("img")).toHaveCount(0);
});

test("removing the picture asks the server and falls back to letters", async ({ page }) => {
  const session = await setup(page, { avatarUrl: `${ORIGIN}/api/v1/media/avatar.png` });
  const menu = await openMenu(page);
  await expect(menu.locator("img")).toHaveCount(1);
  await menu.getByRole("button", { name: /Remove|إزالة/ }).click();
  await expect(menu.getByText("Profile picture removed.")).toBeVisible();
  expect(session.avatarUploads.map((upload) => upload.method)).toEqual(["DELETE"]);
  await expect(menu.locator("img")).toHaveCount(0);
  await expect(menu.locator('[aria-hidden="true"]').filter({ hasText: "HA" })).toBeVisible();
});

test("theme and language live in the menu and change the app", async ({ page }) => {
  await setup(page);
  const menu = await openMenu(page);
  await expect(page.locator("html")).not.toHaveClass(/(^|\s)dark(\s|$)/);
  await menu.getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveClass(/(^|\s)dark(\s|$)/);
  await expect(menu.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");

  await menu.getByRole("button", { name: "Arabic" }).click();
  await expect(menu.getByRole("button", { name: /الإعدادات/ })).toBeVisible();
  await expect(menu.getByRole("button", { name: /تسجيل الخروج/ })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("salesos.lang"))).toBe("ar");
  expect(await page.evaluate(() => localStorage.getItem("salesos.theme"))).toBe("dark");
});

test("the header no longer carries theme and language switches", async ({ page }) => {
  await setup(page);
  await page.goto("/dashboard");
  await expect(page.locator("header button").filter({ has: page.locator("svg.lucide-languages") })).toHaveCount(0);
  await expect(page.locator("header button").filter({ has: page.locator("svg.lucide-moon, svg.lucide-sun") })).toHaveCount(0);
});

test("signing out calls the server once and leaves the app", async ({ page }) => {
  const session = await setup(page);
  const menu = await openMenu(page);
  await menu.getByRole("button", { name: /Sign out|تسجيل الخروج/ }).click();
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  expect(session.logouts).toBe(1);
});
