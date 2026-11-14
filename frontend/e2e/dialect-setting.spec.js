import { expect, test } from "@playwright/test";

// UI contract: only HTTP transport is mocked, but the mock KEEPS STATE like the server does, so a
// save followed by a reload reads back what was written. No backend persistence claim beyond that.
const CHOICES = ["egyptian", "gulf", "levantine", "maghrebi", "msa"];
const SOURCE_FOR = { EGP: "egyptian", SAR: "gulf" };
const json = (route, data, status = 200) => route.fulfill({ status, json: data });

async function setup(page, { stored = null, currency = "EGP", lang = "en", failPut = null, failGet = false, hold = false, rewrite = null } = {}) {
  const state = { dialect: stored, puts: [], currencyPuts: 0, release: () => {} };
  const gate = new Promise((resolve) => { state.release = resolve; });
  const info = () => {
    const mapped = SOURCE_FOR[currency];
    return {
      tenant_id: "tenant",
      dialect: state.dialect,
      effective: state.dialect || mapped || "msa",
      source: state.dialect ? "owner" : mapped ? "currency" : "default",
      choices: CHOICES,
    };
  };
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(process.env.BASE_URL || "http://127.0.0.1:4173").origin }]);
  await page.addInitScript((locale) => localStorage.setItem("salesos.lang", locale), lang);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/auth/me") return json(route, { id: "user", email: "ui@example.com", full_name: "Merchant", is_active: true, tenants: [{ id: "tenant", name: "Shop", role_code: "owner" }] });
    if (path === "/api/v1/tenants/tenant/currency") {
      if (request.method() === "PUT") state.currencyPuts += 1;
      return json(route, { currency });
    }
    if (path === "/api/v1/tenants/tenant/timezone") return json(route, { timezone: null });
    if (path === "/api/v1/tenants/tenant/dialect") {
      if (request.method() === "PUT") {
        const body = request.postDataJSON();
        state.puts.push(body);
        if (hold) await gate;
        if (failPut) return json(route, { detail: failPut }, 400);
        // the server decides what is stored: a mock that rewrites the value proves the screen
        // shows the server's answer, not the owner's pick
        state.dialect = body.dialect === "levantine" && rewrite ? rewrite : (body.dialect ?? null);
        return json(route, info());
      }
      return failGet ? json(route, { detail: "boom" }, 500) : json(route, info());
    }
    return json(route, {});
  });
  await page.goto("/settings");
  return state;
}

// SettingCard is a plain <section> with an <h2>, so the card is the section holding that heading.
const card = (page, title = "Assistant dialect") =>
  page.locator("section").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
const pick = async (page, name) => {
  await page.getByTestId("dialect-select").click();
  await page.getByRole("option", { name, exact: true }).click();
};

test("a shop that never chose sees Automatic and which dialect that means", async ({ page }) => {
  await setup(page, { currency: "EGP" });
  await expect(page.getByTestId("dialect-select")).toContainText("Automatic (from currency)");
  await expect(card(page)).toContainText("In use now: Egyptian (from your currency)");
  await expect(page.getByTestId("dialect-save")).toBeDisabled();
});

test("choosing a dialect saves exactly that key and confirms only after the server answers", async ({ page }) => {
  const state = await setup(page, { currency: "EGP", hold: true });
  await pick(page, "Gulf");
  await expect(page.getByTestId("dialect-save")).toBeEnabled();
  await expect(page.getByTestId("dialect-message")).toHaveCount(0);
  await page.getByTestId("dialect-save").click();
  // the request is out and unanswered: the screen must not claim a save, and must show it is busy
  await expect.poll(() => state.puts.length).toBe(1);
  await expect(page.getByTestId("dialect-message")).toHaveCount(0);
  await expect(page.getByTestId("dialect-save")).toBeDisabled();
  await expect(card(page)).toContainText("In use now: Egyptian");
  state.release();
  await expect(page.getByTestId("dialect-message")).toHaveText("Assistant dialect saved.");
  expect(state.puts).toEqual([{ dialect: "gulf" }]);
  await expect(card(page)).toContainText("In use now: Gulf (chosen by you)");
  await expect(page.getByTestId("dialect-save")).toBeDisabled();
  await page.reload();
  await expect(page.getByTestId("dialect-select")).toContainText("Gulf");
});

test("Automatic sends an explicit null so the choice is cleared, not left alone", async ({ page }) => {
  const state = await setup(page, { stored: "gulf", currency: "EGP" });
  await expect(page.getByTestId("dialect-select")).toContainText("Gulf");
  await pick(page, "Automatic (from currency)");
  await page.getByTestId("dialect-save").click();
  await expect(page.getByTestId("dialect-message")).toBeVisible();
  expect(state.puts).toEqual([{ dialect: null }]);
  expect("dialect" in state.puts[0]).toBe(true);
  await expect(card(page)).toContainText("In use now: Egyptian (from your currency)");
});

test("a refused save shows the server's reason and claims nothing", async ({ page }) => {
  const state = await setup(page, { failPut: "unknown dialect" });
  await pick(page, "Levantine");
  await page.getByTestId("dialect-save").click();
  await expect(page.getByTestId("dialect-message")).toContainText(/unknown dialect|Could not save/);
  await expect(page.getByTestId("dialect-message")).not.toHaveText("Assistant dialect saved.");
  expect(state.puts).toEqual([{ dialect: "levantine" }]);
  await expect(card(page)).toContainText("In use now: Egyptian");
});

test("if the setting cannot be loaded, the screen cannot write over it", async ({ page }) => {
  const state = await setup(page, { failGet: true });
  await expect(page.getByTestId("dialect-message")).toBeVisible();
  await expect(page.getByTestId("dialect-save")).toBeDisabled();
  await expect(page.getByTestId("dialect-select")).toBeDisabled();
  expect(state.puts).toEqual([]);
});

test("saving the regional settings never touches the assistant's dialect", async ({ page }) => {
  const state = await setup(page, { stored: "msa", currency: "EGP" });
  const regional = card(page, "Regional settings");
  await regional.getByRole("button", { name: "Save changes" }).click();
  // wait for the WHOLE regional save to finish (its own confirmation), not just its first request:
  // a stray dialect write would come after the currency and timezone writes
  await expect(regional.getByText("Workspace currency and time zone were saved.")).toBeVisible();
  expect(state.currencyPuts).toBe(1);
  // ...and it wrote no dialect, so changing the country cannot rewrite how the assistant talks
  expect(state.puts).toEqual([]);
  await expect(page.getByTestId("dialect-select")).toContainText("Simple Modern Standard");
});

test("Arabic: the card, the options and the confirmation are in Arabic", async ({ page }) => {
  await setup(page, { lang: "ar", currency: "EGP" });
  await expect(card(page, "لهجة المساعد")).toBeVisible();
  await expect(page.getByTestId("dialect-select")).toContainText("تلقائي (حسب العملة)");
  await page.getByTestId("dialect-select").click();
  await page.getByRole("option", { name: "خليجية", exact: true }).click();
  await page.getByTestId("dialect-save").click();
  await expect(page.getByTestId("dialect-message")).toHaveText("اتحفظت لهجة المساعد.");
});

test("mobile: the dialect card fits without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await setup(page);
  await expect(page.getByTestId("dialect-select")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("after a save the screen shows what the server now holds, not what was picked", async ({ page }) => {
  await setup(page, { currency: "EGP", rewrite: "msa" });
  await pick(page, "Levantine");
  await page.getByTestId("dialect-save").click();
  await expect(page.getByTestId("dialect-message")).toBeVisible();
  await expect(page.getByTestId("dialect-select")).toContainText("Simple Modern Standard");
  await expect(page.getByTestId("dialect-select")).not.toContainText("Levantine");
  await expect(card(page)).toContainText("In use now: Simple Modern Standard (chosen by you)");
});
