import { expect, test } from "@playwright/test";

// Every icon-only button in the app shell must have an accessible name: a screen reader otherwise
// announces "button" and nothing else. Only HTTP is mocked.
const json = (route, data, status = 200) => route.fulfill({ status, json: data });

async function open(page, path, { lang = "ar", width = 390, extra = null } = {}) {
  await page.setViewportSize({ width, height: 800 });
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(process.env.BASE_URL || "http://127.0.0.1:4173").origin }]);
  await page.addInitScript((l) => localStorage.setItem("salesos.lang", l), lang);
  await page.route("**/api/v1/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    // one catch-all route only (Playwright tries the newest route first), so extras go through here
    const handled = extra && extra(route, p);
    if (handled) return handled;
    if (p === "/api/v1/auth/me") return json(route, { id: "u", email: "ui@example.com", full_name: "Merchant", is_active: true, tenants: [{ id: "tenant", name: "Shop", role_code: "owner" }] });
    return json(route, route.request().method() === "GET" && /s$/.test(p) ? [] : {});
  });
  await page.goto(path);
  await page.waitForTimeout(800);
}

// Visible buttons that have neither text, aria-label, title nor aria-labelledby.
const unnamed = (page) => page.evaluate(() => [...document.querySelectorAll("button")]
  .filter((b) => {
    const r = b.getBoundingClientRect();
    if (!r.width || !r.height) return false;
    return !(b.getAttribute("aria-label") || b.getAttribute("aria-labelledby") || b.title || b.innerText.trim());
  })
  .map((b) => (b.className || "").toString().slice(0, 70)));

for (const lang of ["ar", "en"]) {
  for (const [name, path] of [["dashboard", "/dashboard"], ["settings", "/settings"], ["settings-ai", "/settings/ai"], ["inbox", "/inbox"]]) {
    for (const width of [390, 1366]) {
      test(`${lang} ${name} @${width}: every visible button has a name`, async ({ page }) => {
        await open(page, path, { lang, width });
        expect(await unnamed(page)).toEqual([]);
      });
    }
  }
}

test("the menu button opens the drawer and names itself", async ({ page }) => {
  await open(page, "/dashboard", { lang: "en" });
  const menu = page.getByRole("button", { name: "Open menu", exact: true });
  await expect(menu).toBeVisible();
  await menu.click();
  await expect(page.getByRole("link", { name: "Customers" }).first()).toBeInViewport();
});

// The bell shows a number badge, which is only a visual cue: the button's own name must carry it.
async function bell(page, count) {
  await open(page, "/dashboard", {
    lang: "en",
    width: 1366,
    extra: (route, p) => {
      if (p === "/api/v1/notifications/unread-count") return json(route, { count });
      if (p === "/api/v1/notifications") return json(route, []);
      return null;
    },
  });
}

test("the notifications button says how many are unread", async ({ page }) => {
  await bell(page, 3);
  await expect(page.getByRole("button", { name: "Notifications (3)", exact: true })).toBeVisible();
});

test("a count above 99 is capped the same way the badge caps it", async ({ page }) => {
  await bell(page, 250);
  await expect(page.getByRole("button", { name: "Notifications (99+)", exact: true })).toBeVisible();
});

test("with nothing unread the name is just Notifications", async ({ page }) => {
  await bell(page, 0);
  await expect(page.getByRole("button", { name: "Notifications", exact: true })).toBeVisible();
});

test("the help button names itself and opens its menu", async ({ page }) => {
  await open(page, "/dashboard", { lang: "en", width: 1366 });
  const help = page.getByRole("button", { name: "Help", exact: true });
  await expect(help).toHaveAttribute("aria-expanded", "false");
  await help.click();
  await expect(help).toHaveAttribute("aria-expanded", "true");
});
