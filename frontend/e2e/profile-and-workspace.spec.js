import { expect, test } from "@playwright/test";

// The split this spec protects: the profile answers "who am I", the workspace answers "what is
// this shop". They used to be one page, so a person's name and the shop's currency sat under the
// same heading, and the assistant's dialect sat there too. Only HTTP is mocked, and the mock keeps
// state, so a save followed by a reload reads back what the server now holds.
const json = (route, data, status = 200) => route.fulfill({ status, json: data });

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==",
  "base64",
);

async function setup(page, { lang = "en" } = {}) {
  const state = {
    fullName: "Merchant",
    tenantName: "Shop",
    namePuts: [],
    tenantNamePuts: [],
    avatarPuts: 0,
    avatarUrl: null,
    currencyPuts: 0,
  };
  await page.context().addCookies([
    { name: "csrf_token", value: "ui-test", url: new URL(process.env.BASE_URL || "http://127.0.0.1:4173").origin },
  ]);
  await page.addInitScript((locale) => localStorage.setItem("salesos.lang", locale), lang);
  const me = () => ({
    id: "user",
    email: "owner@example.com",
    full_name: state.fullName,
    avatar_url: state.avatarUrl,
    is_active: true,
    tenants: [{ id: "tenant", name: state.tenantName, slug: "shop-1", role_code: "owner" }],
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path === "/api/v1/auth/me") return json(route, me());
    if (path === "/api/v1/users/me" && request.method() === "PATCH") {
      const body = request.postDataJSON();
      state.namePuts.push(body);
      // the server owns the stored value: collapse the whitespace and refuse to echo the input
      state.fullName = String(body.full_name).trim().replace(/\s+/g, " ");
      return json(route, me());
    }
    if (path === "/api/v1/users/me/avatar" && request.method() === "PUT") {
      state.avatarPuts += 1;
      state.avatarUrl = "/media/avatars/user.png";
      return json(route, me());
    }
    if (path === "/api/v1/tenants/tenant/name" && request.method() === "PUT") {
      const body = request.postDataJSON();
      state.tenantNamePuts.push(body);
      state.tenantName = String(body.name).trim().replace(/\s+/g, " ");
      return json(route, { tenant_id: "tenant", name: state.tenantName });
    }
    if (path === "/api/v1/tenants/tenant/currency") {
      if (request.method() === "PUT") state.currencyPuts += 1;
      return json(route, { currency: "EGP" });
    }
    if (path === "/api/v1/tenants/tenant/timezone") return json(route, { timezone: null });
    if (path === "/api/v1/ai/agents" || path === "/api/v1/ai/agent-kinds") return json(route, []);
    if (path === "/api/v1/ai/approvals") return json(route, { items: [], truncated: false });
    if (path === "/api/v1/ai/usage/summary") return json(route, { totals: { tokens_in: 0, tokens_out: 0 } });
    return json(route, {});
  });
  return state;
}

const sidebar = (page) => page.getByRole("navigation");

test("the profile is the person: picture, name and email, and nothing about the shop", async ({ page }) => {
  await setup(page);
  await page.goto("/settings");

  await expect(page.getByTestId("profile-name")).toHaveValue("Merchant");
  await expect(page.getByText("owner@example.com")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add profile picture" })).toBeVisible();

  // the shop's regional settings and the assistant's dialect used to live here; they do not now
  await expect(page.getByRole("heading", { name: "Regional settings" })).toHaveCount(0);
  await expect(page.getByTestId("dialect-select")).toHaveCount(0);
  await expect(page.locator('select, [role="combobox"]')).toHaveCount(0);

  // the shop's name is not a personal setting either: no row, no link to it from here
  await expect(page.getByRole("link", { name: "Workspace settings" })).toHaveCount(0);

  // the person's own preferences are one click away, on the one page that owns them
  const preferences = page.getByRole("link", { name: "Open preferences" });
  await expect(preferences).toBeVisible();
  await preferences.click();
  await expect(page).toHaveURL(/\/settings\/preferences$/);

  // and they really are the person's: theme applies to the screen, language to the whole app
  await expect(page.getByTestId("prefs-language")).toBeVisible();
  await page.getByTestId("prefs-theme").getByRole("radio", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByTestId("prefs-language").getByRole("radio", { name: "العربية" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "التفضيلات" })).toBeVisible();
});

test("a renamed profile saves once, and the page shows what the server stored", async ({ page }) => {
  const state = await setup(page);
  await page.goto("/settings");

  const input = page.getByTestId("profile-name");
  const save = page.getByTestId("profile-name-save");

  // nothing to save until the name actually changes
  await expect(save).toBeDisabled();

  await input.fill("  New   Name  ");
  await expect(save).toBeEnabled();
  await save.click();

  await expect(page.getByTestId("profile-name-message")).toHaveText("Name saved.");
  expect(state.namePuts).toEqual([{ full_name: "  New   Name  " }]);
  // the whitespace the server collapsed comes back to the field, so the screen never claims a
  // value that is not stored
  await expect(input).toHaveValue("New Name");
  await expect(save).toBeDisabled();
});

test("uploading a picture from the profile writes the avatar and confirms", async ({ page }) => {
  const state = await setup(page);
  await page.goto("/settings");

  await page.locator('input[type="file"]').setInputFiles({
    name: "me.png",
    mimeType: "image/png",
    buffer: PNG,
  });

  await expect.poll(() => state.avatarPuts).toBe(1);
  await expect(page.getByText("Profile picture updated.")).toBeVisible();
});

test("the workspace owns the shop's name, currency and time zone — and not the person", async ({ page }) => {
  const state = await setup(page);
  // the overview is a hub; the name, currency and zone are edited on its Workspace data page
  await page.goto("/settings/workspace/data");

  await expect(page.getByTestId("workspace-name")).toHaveValue("Shop");
  await expect(page.getByRole("heading", { name: "Regional settings" })).toBeVisible();
  // the person's own name is not editable here, and neither is the assistant's dialect
  await expect(page.getByTestId("profile-name")).toHaveCount(0);
  await expect(page.getByTestId("dialect-select")).toHaveCount(0);

  const input = page.getByTestId("workspace-name");
  const save = page.getByTestId("workspace-name-save");
  await expect(save).toBeDisabled();

  await input.fill("Fihrist Store");
  await save.click();

  await expect(page.getByTestId("workspace-name-message")).toHaveText("Workspace name saved.");
  // the shop is renamed through the tenant, never through the user
  expect(state.tenantNamePuts).toEqual([{ name: "Fihrist Store" }]);
  expect(state.namePuts).toEqual([]);
  await expect(input).toHaveValue("Fihrist Store");
});

test("the settings sidebar is the map's five groups, and every section is reachable", async ({
  page,
}) => {
  await setup(page);
  await page.goto("/settings");

  // The Center is `docs/settings/center-map.md`'s twenty sections in five groups, generated from
  // `settingsManifest.js`. This assertion used to pin the sidebar's own hand-written six groups
  // ("My account", "Store", "Operations", "Plan & data"), which is how sections that existed in
  // the router — team, customers, analytics, automation, workspace notifications, data — were
  // never reachable from the navigation at all.
  for (const group of [
    "Account & administration",
    "Business & structure",
    "Commerce & operations",
    "Channels & intelligence",
    "Advanced administration",
  ]) {
    await expect(sidebar(page).getByText(group, { exact: true })).toBeVisible();
  }

  // Every section that used to be router-only is now a destination a person can click.
  for (const [label, path] of [
    ["Team & permissions", /\/settings\/team\/members$/],
    // customer-records is a link-away tab to /customers, so the section opens on customer-data
    ["Customers & support", /\/settings\/customers\/customer-data$/],
    ["Analytics & reports", /\/settings\/analytics\/reports$/],
    ["Automation & workflows", /\/settings\/automation\/workflows$/],
    ["Workspace notifications", /\/settings\/notifications\/notification-channels$/],
    ["Data & privacy", /\/settings\/data\/data-privacy$/],
  ]) {
    await sidebar(page).getByRole("link", { name: label, exact: true }).click();
    await expect(page).toHaveURL(path);
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await page.goto("/settings");
  }

  // The old combined team screen is not a second front door: the address forwards to section 03.
  await page.goto("/settings/members");
  await expect(page).toHaveURL(/\/settings\/team\/members$/);
  await expect(
    sidebar(page).getByRole("link", { name: "Members & roles", exact: true })
  ).toHaveCount(0);
});

test("Arabic: the profile and the workspace speak Arabic", async ({ page }) => {
  await setup(page, { lang: "ar" });
  await page.goto("/settings");

  await expect(page.getByRole("heading", { level: 1, name: "الملف الشخصي" })).toBeVisible();
  await expect(page.getByRole("button", { name: "إضافة صورة شخصية" })).toBeVisible();
  await expect(page.getByRole("link", { name: "افتح التفضيلات" })).toBeVisible();

  await page.goto("/settings/workspace/data");
  await expect(page.getByTestId("workspace-name-save")).toContainText("حفظ");
});

test("mobile: neither page scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);

  for (const path of ["/settings", "/settings/workspace", "/settings/workspace/data"]) {
    await page.goto(path);
    await page.getByRole("heading", { level: 1 }).first().waitFor();
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${path} must fit 390px`).toBeLessThanOrEqual(1);
  }
});
