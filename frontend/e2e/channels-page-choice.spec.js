import { expect, test } from "@playwright/test";

// The owner ticked several Pages in Meta's window. The connect pauses and asks which; only the
// chosen Page is connected, and a refusal is shown instead of a false "connected". The callback page
// reaches this page over the BroadcastChannel it also uses for "connected" and errors.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const json = (route, data, status = 200) => route.fulfill({ status, json: data });
const CHOOSE = { ticket: "T".repeat(24), provider: "facebook", pages: [{ id: "111", name: "Shop One" }, { id: "222", name: "Shop Two" }] };

async function open(page, { chooseReply }) {
  const posted = [];
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.addInitScript(() => {
    window.FB = { init() {}, login() {} };
  });
  await page.route("**/api/v1/**", (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path === "/api/v1/auth/me") return json(route, { id: "u", email: "t@e.com", full_name: "T", is_active: true, tenants: [{ id: "tenant", name: "Shop", role_code: "owner" }] });
    if (path === "/api/v1/integrations/meta/oauth/choose-page") {
      posted.push(JSON.parse(req.postData() || "{}"));
      return chooseReply(route);
    }
    return json(route, []);
  });
  await page.goto("/settings/channels");
  await expect(page.getByRole("button", { name: /^(Connect|ربط)$/ }).first()).toBeVisible();
  return posted;
}

const announce = (page, choose) =>
  page.evaluate((payload) => {
    const bc = new BroadcastChannel("meta_oauth");
    bc.postMessage({ type: "META_OAUTH_RESULT", choose: payload });
    bc.close();
  }, choose);

test("several Pages open a chooser that connects only the Page picked", async ({ page }) => {
  const posted = await open(page, { chooseReply: (r) => json(r, { connected: "facebook:Shop Two" }) });
  await announce(page, CHOOSE);

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Shop One")).toBeVisible();
  await expect(dialog.getByText("Shop Two")).toBeVisible();

  // Nothing is picked for the owner, and nothing can be sent until they pick.
  await expect(dialog.getByRole("radio", { checked: true })).toHaveCount(0);
  const connect = dialog.getByRole("button", { name: /Connect this Page|ربط هذه الصفحة/ });
  await expect(connect).toBeDisabled();

  await dialog.getByText("Shop Two").click();
  await expect(connect).toBeEnabled();
  await connect.click();

  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0]).toEqual({ ticket: CHOOSE.ticket, page_id: "222" });
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText(/Shop Two/).first()).toBeVisible();
});

test("a refused choice stays open with the reason and connects nothing", async ({ page }) => {
  await open(page, { chooseReply: (r) => json(r, { detail: "This choice expired. Press connect again." }, 422) });
  await announce(page, CHOOSE);
  const dialog = page.getByRole("dialog");
  await dialog.getByText("Shop One").click();
  await dialog.getByRole("button", { name: /Connect this Page|ربط هذه الصفحة/ }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(dialog).toBeVisible();
});

test("cancelling closes the chooser without sending anything", async ({ page }) => {
  const posted = await open(page, { chooseReply: (r) => json(r, {}) });
  await announce(page, CHOOSE);
  await page.getByRole("dialog").getByRole("button", { name: /Cancel|إلغاء/ }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(posted).toEqual([]);
});

test("a single Page is not a choice, so no chooser opens", async ({ page }) => {
  await open(page, { chooseReply: (r) => json(r, {}) });
  await announce(page, { ...CHOOSE, pages: [CHOOSE.pages[0]] });
  await page.waitForTimeout(500);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
