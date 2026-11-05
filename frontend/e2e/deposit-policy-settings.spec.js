import { expect, test } from "@playwright/test";

// UI contract tests: only HTTP transport is mocked; no backend persistence claim.
const savedPolicy = {
  id: "policy-2", name: "Standard deposit", version: 2, is_active: true,
  deposit_type: "percentage", deposit_value: "25.00", currency: "SAR",
  calculation_base: "items_after_discounts", minimum_deposit: "10.00", maximum_deposit: "500.00",
  created_at: "2026-11-05T10:00:00Z", updated_at: "2026-11-05T10:00:00Z",
};
const textKeys = ["exchange", "return", "shipping", "hours", "ordering", "cancellation"];
const json = (route, data, status = 200) => route.fulfill({ status, json: data });

async function setup(page, { policies = [], currency = "SAR", lang = "en", get, post, getCurrency, tenants = [{ id: "tenant", name: "Shop", role_code: "owner" }] } = {}) {
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(process.env.BASE_URL || "http://127.0.0.1:4173").origin }]);
  await page.addInitScript((locale) => localStorage.setItem("salesos.lang", locale), lang);
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/auth/me") return json(route, { id: "user", email: "ui@example.com", full_name: "Merchant", is_active: true, tenants });
    if (path === "/api/v1/tenants/tenant/currency") return getCurrency ? getCurrency(route) : json(route, { currency });
    if (path === "/api/v1/orders/deposit-policies") {
      if (route.request().method() === "POST") return post ? post(route) : json(route, savedPolicy, 201);
      return get ? get(route) : json(route, policies);
    }
    if (path === "/api/v1/ai/store-policies") return json(route, { max_chars: 1500, items: textKeys.map((key) => ({ key, title: "عنوان عربي من الخادم", content: "", published: false })) });
    if (path.startsWith("/api/v1/ai/store-policies/")) return json(route, { ...route.request().postDataJSON(), published: true });
    return json(route, {});
  });
  await page.goto("/settings/policies");
}
const card = (page) => page.getByRole("region", { name: "Deposit policy" });
async function choose(page, label, option) {
  await page.getByRole("combobox", { name: label, exact: true }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}
async function draft(page, type = "Percentage") {
  await card(page).getByLabel("Policy name", { exact: true }).fill("Standard deposit");
  await choose(page, "Deposit type", type);
}

test("empty is unconfigured, never an implicit no-deposit policy; units use authoritative currency", async ({ page }) => {
  await setup(page);
  await expect(card(page).getByText("Not configured", { exact: true })).toBeVisible();
  await expect(card(page).getByText(/Saving only stores settings/)).toBeVisible();
  await expect(card(page).getByRole("button", { name: "Save new version" })).toBeDisabled();
  await expect(card(page).getByRole("combobox", { name: "Deposit type" })).toContainText("Choose a type");
  await draft(page, "Fixed amount");
  await expect(card(page).getByLabel("Deposit value (SAR)", { exact: true })).toBeVisible();
  await expect(card(page)).not.toContainText("EGP");
});

test("golden percentage saves exact contract, renders server version, and reloads history", async ({ page }, testInfo) => {
  let persisted = false;
  const bodies = [];
  await setup(page, {
    get: (route) => json(route, persisted ? [savedPolicy, { ...savedPolicy, id: "policy-1", version: 1, is_active: false, name: "Old policy" }] : []),
    post: (route) => { bodies.push(route.request().postDataJSON()); persisted = true; return json(route, savedPolicy, 201); },
  });
  await draft(page);
  await card(page).getByLabel("Deposit value (%)", { exact: true }).fill("25.00");
  await choose(page, "Calculation base", "Items after discounts");
  await card(page).getByLabel("Minimum deposit (SAR, optional)", { exact: true }).fill("10.00");
  await card(page).getByLabel("Maximum deposit (SAR, optional)", { exact: true }).fill("500.00");
  await card(page).getByRole("button", { name: "Save new version" }).click();
  await expect(card(page).getByText("Policy settings saved.")).toBeVisible();
  expect(bodies).toEqual([{ name: "Standard deposit", deposit_type: "percentage", deposit_value: "25.00", calculation_base: "items_after_discounts", minimum_deposit: "10.00", maximum_deposit: "500.00" }]);
  await expect(card(page).getByText("Active version: 2", { exact: true })).toBeVisible();
  await expect(card(page).getByRole("button", { name: "Save new version" })).toBeDisabled();
  await page.reload();
  await expect(card(page).getByLabel("Deposit value (%)", { exact: true })).toHaveValue("25.00");
  await expect(card(page).getByText(/Old policy/)).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("deposit-golden.png"), fullPage: true });
});

test("numeric validation blocks blanks, nonfinite, nonpositive, excessive precision and invalid bands", async ({ page }) => {
  const bodies = [];
  await setup(page, { post: (route) => { bodies.push(route.request().postDataJSON()); return json(route, savedPolicy); } });
  await draft(page);
  const value = card(page).getByLabel("Deposit value (%)", { exact: true });
  const save = card(page).getByRole("button", { name: "Save new version" });
  for (const invalid of ["", " ", "0", "-1", "101", "1.001", "Infinity", "1e309", "NaN"]) {
    await value.fill(invalid);
    await expect(save).toBeDisabled();
  }
  await value.fill("100");
  await expect(save).toBeEnabled();
  const min = card(page).getByLabel("Minimum deposit (SAR, optional)", { exact: true });
  const max = card(page).getByLabel("Maximum deposit (SAR, optional)", { exact: true });
  for (const invalid of ["-1", "1.001", "Infinity"]) {
    await min.fill(invalid);
    await expect(save).toBeDisabled();
  }
  await min.fill("20");
  await max.fill("10");
  await expect(save).toBeDisabled();
  await min.fill("0");
  await max.fill("0");
  await expect(save).toBeEnabled();
  expect(bodies).toEqual([]);
});

test("failed save preserves dirty draft and disables all fields while pending; retry succeeds", async ({ page }) => {
  let release;
  let attempts = 0;
  const bodies = [];
  const gate = new Promise((resolve) => { release = resolve; });
  await setup(page, { post: async (route) => {
    bodies.push(route.request().postDataJSON());
    attempts += 1;
    if (attempts === 1) { await gate; return json(route, { error: { code: "unavailable", message: "Internal service detail", retryable: true } }, 503); }
    return json(route, { ...savedPolicy, deposit_type: "fixed", deposit_value: "75.50", minimum_deposit: null, maximum_deposit: null }, 201);
  } });
  await draft(page, "Fixed amount");
  await card(page).getByLabel("Deposit value (SAR)", { exact: true }).fill("75.50");
  await card(page).getByRole("button", { name: "Save new version" }).click();
  await expect(card(page).getByLabel("Policy name", { exact: true })).toBeDisabled();
  await expect(card(page).getByRole("combobox", { name: "Deposit type" })).toBeDisabled();
  await expect(card(page).getByLabel("Deposit value (SAR)", { exact: true })).toBeDisabled();
  await expect(card(page).getByLabel("Minimum deposit (SAR, optional)", { exact: true })).toBeDisabled();
  release();
  await expect(card(page).getByRole("alert")).toContainText("Could not save deposit policy");
  await expect(card(page).getByLabel("Deposit value (SAR)", { exact: true })).toHaveValue("75.50");
  await expect(card(page).getByText("Unsaved changes")).toBeVisible();
  await card(page).getByRole("button", { name: "Save new version" }).click();
  await expect(card(page).getByText("Policy settings saved.")).toBeVisible();
  expect(bodies).toHaveLength(2);
  for (const body of bodies) expect(body).toEqual({ name: "Standard deposit", deposit_type: "fixed", deposit_value: "75.50", calculation_base: "grand_total", minimum_deposit: null, maximum_deposit: null });
});

test("loading and load error are not empty; retry recovers", async ({ page }, testInfo) => {
  let release;
  let attempts = 0;
  const gate = new Promise((resolve) => { release = resolve; });
  await setup(page, { get: async (route) => {
    attempts += 1;
    if (attempts === 1) { await gate; return json(route, { detail: "Unavailable" }, 503); }
    return json(route, []);
  } });
  await expect(card(page).getByRole("status")).toContainText("Loading deposit policies");
  await expect(card(page).getByText("Not configured", { exact: true })).toHaveCount(0);
  release();
  await expect(card(page).getByRole("alert")).toContainText("Could not load deposit policies");
  await expect(card(page).getByLabel("Policy name", { exact: true })).toHaveCount(0);
  await card(page).screenshot({ path: testInfo.outputPath("deposit-error.png") });
  await card(page).getByRole("button", { name: "Retry" }).click();
  await expect(card(page).getByText("Not configured", { exact: true })).toBeVisible();
});

test("explicit none clears value and bands in the request", async ({ page }) => {
  let body;
  await setup(page, { policies: [savedPolicy], post: (route) => {
    body = route.request().postDataJSON();
    return json(route, { ...savedPolicy, ...body, version: 3 });
  } });
  await choose(page, "Deposit type", "No deposit");
  await expect(card(page).getByLabel(/Deposit value/)).toHaveCount(0);
  await card(page).getByRole("button", { name: "Save new version" }).click();
  await expect(card(page).getByText("Active version: 3", { exact: true })).toBeVisible();
  expect(body).toEqual({ name: "Standard deposit", deposit_type: "none", deposit_value: "0", calculation_base: "grand_total", minimum_deposit: null, maximum_deposit: null });
});

for (const type of ["fixed", "percentage"]) {
  test(`currency mismatch ${type}: clear money, preserve rate and require acknowledgement`, async ({ page }, testInfo) => {
    let body;
    await setup(page, { currency: "EGP", policies: [{ ...savedPolicy, deposit_type: type }], post: (route) => {
      body = route.request().postDataJSON();
      return json(route, { ...savedPolicy, ...body, currency: "EGP", version: 3 }, 201);
    } });
    await expect(card(page).getByRole("alert")).toContainText("SAR");
    await expect(card(page).getByRole("alert")).toContainText("EGP");
    const value = card(page).getByLabel(`Deposit value (${type === "fixed" ? "EGP" : "%"})`, { exact: true });
    await expect(value).toHaveValue(type === "fixed" ? "" : "25.00");
    await expect(card(page).getByLabel("Minimum deposit (EGP, optional)", { exact: true })).toHaveValue("");
    await expect(card(page).getByLabel("Maximum deposit (EGP, optional)", { exact: true })).toHaveValue("");
    const save = card(page).getByRole("button", { name: "Save new version" });
    await expect(save).toBeDisabled();
    if (type === "fixed") await value.fill("90.50");
    await expect(save).toBeDisabled();
    expect(body).toBeUndefined();
    await card(page).screenshot({ path: testInfo.outputPath(`deposit-currency-${type}.png`) });
    await card(page).getByRole("checkbox", { name: /I have reviewed.*EGP/ }).check();
    await expect(save).toBeEnabled();
    if (type === "fixed") await card(page).getByLabel("Minimum deposit (EGP, optional)", { exact: true }).fill("10.00");
    await save.click();
    await expect(card(page).getByText("Policy settings saved.")).toBeVisible();
    expect(body).toEqual({ name: "Standard deposit", deposit_type: type, deposit_value: type === "fixed" ? "90.50" : "25.00", calculation_base: type === "fixed" ? "grand_total" : "items_after_discounts", minimum_deposit: type === "fixed" ? "10.00" : null, maximum_deposit: null });
    await expect(card(page).getByRole("checkbox")).toHaveCount(0);
  });
}

for (const failure of ["missing", "unavailable", "forbidden", "ambiguous tenant"]) {
  test(`currency load ${failure}: fail closed without guessing from active policy`, async ({ page }, testInfo) => {
    let posts = 0;
    await setup(page, {
      policies: [savedPolicy], currency: null,
      ...(failure === "ambiguous tenant" ? { tenants: [{ id: "tenant" }, { id: "other" }] } : {}),
      getCurrency: failure === "unavailable" || failure === "forbidden" ? (route) => json(route, { error: { code: failure === "forbidden" ? "permission_denied" : "unavailable", message: "Private detail", retryable: failure === "unavailable" } }, failure === "forbidden" ? 403 : 503) : undefined,
      post: (route) => { posts += 1; return json(route, savedPolicy); },
    });
    await expect(card(page).getByRole("alert")).toContainText(failure === "forbidden" ? "permission" : "currency");
    await expect(card(page).getByRole("button", { name: "Save new version" })).toHaveCount(0);
    await expect(card(page).getByLabel("Policy name", { exact: true })).toHaveCount(0);
    await expect(card(page).getByRole("button", { name: "Retry" })).toHaveCount(failure === "unavailable" ? 1 : 0);
    await expect(card(page)).not.toContainText("Private detail");
    expect(posts).toBe(0);
    await card(page).screenshot({ path: testInfo.outputPath(`deposit-currency-${failure.replaceAll(" ", "-")}.png`) });
  });
}

test("name and money bounds reject overflow with actionable validation", async ({ page }) => {
  await setup(page, { policies: [savedPolicy] });
  const name = card(page).getByLabel("Policy name", { exact: true });
  const save = card(page).getByRole("button", { name: "Save new version" });
  await name.fill("N".repeat(128));
  await expect(save).toBeDisabled();
  await expect(card(page).getByText(/127/)).toBeVisible();
  await name.fill("N".repeat(127));
  await expect(save).toBeEnabled();
  await choose(page, "Deposit type", "Fixed amount");
  for (const label of ["Deposit value (SAR)", "Minimum deposit (SAR, optional)", "Maximum deposit (SAR, optional)"]) {
    await card(page).getByLabel("Minimum deposit (SAR, optional)", { exact: true }).fill("");
    await card(page).getByLabel("Maximum deposit (SAR, optional)", { exact: true }).fill("");
    const field = card(page).getByLabel(label, { exact: true });
    await field.fill("1000000000");
    await expect(save).toBeDisabled();
    await expect(card(page).getByText(/999999999\.99/)).toBeVisible();
    await field.fill("999999999.99");
    await expect(save).toBeEnabled();
  }
});

for (const status of [403, 422, 503]) {
  for (const lang of ["en", "ar"]) {
    test(`save ${status} ${lang}: localized actionable error, no backend text`, async ({ page }) => {
      const isArabic = lang === "ar";
      const name = isArabic ? "اسم السياسة" : "Policy name";
      const saveName = isArabic ? "حفظ إصدار جديد" : "Save new version";
      await setup(page, { lang, policies: [savedPolicy], post: (route) => json(route, {
        error: { code: status === 403 ? "permission_denied" : status === 422 ? "validation_error" : "unavailable", message: "INTERNAL_SECRET_DETAIL", retryable: status === 503, details: { field: "name" } },
      }, status) });
      const region = page.getByRole("region", { name: isArabic ? "سياسة العربون" : "Deposit policy" });
      await region.getByLabel(name, { exact: true }).fill("Edited draft");
      await region.getByRole("button", { name: saveName }).click();
      const alert = region.getByRole("alert");
      await expect(alert).toContainText(status === 403 ? (isArabic ? "صلاحية" : "permission") : status === 422 ? (isArabic ? "راجع" : "Review") : (isArabic ? "حاول" : "try"));
      await expect(region).not.toContainText("INTERNAL_SECRET_DETAIL");
      await expect(region.getByLabel(name, { exact: true })).toHaveValue("Edited draft");
      if (status !== 503) await expect(alert).not.toContainText(/retry|try.*again|حاول/i);
    });
  }
}

for (const lang of ["en", "ar"]) {
  test(`mobile ${lang}: localized text policy keys, placeholders, and deposit controls fit`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setup(page, { lang });
    const titles = lang === "ar" ? ["سياسة الطلب", "سياسة الإلغاء"] : ["Ordering policy", "Cancellation policy"];
    for (const title of titles) {
      await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
      await expect(page.getByRole("textbox", { name: title, exact: true })).not.toHaveAttribute("placeholder", /policies\./);
    }
    const region = page.getByRole("region", { name: lang === "ar" ? "سياسة العربون" : "Deposit policy" });
    await expect(region).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    expect(widths[0]).toBeLessThanOrEqual(widths[1]);
    await region.screenshot({ path: testInfo.outputPath(`deposit-empty-mobile-${lang}.png`) });
  });
}
