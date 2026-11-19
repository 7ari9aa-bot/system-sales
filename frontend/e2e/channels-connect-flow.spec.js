import { expect, test } from "@playwright/test";

// The connect flows on Settings > Channels, end to end with only HTTP and Meta's SDK faked:
// WhatsApp's popup hands back a code AND, separately, a window message with the ids, in either
// order; and the Meta OAuth result banner must only trust our own page.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const json = (route, data, status = 200) => route.fulfill({ status, json: data });

async function open(page, { sdk, arg }) {
  const calls = [];
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(ORIGIN).origin }]);
  await page.addInitScript(sdk, arg);
  await page.route("**/api/v1/**", (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path === "/api/v1/auth/me") return json(route, { id: "u", email: "t@e.com", full_name: "T", is_active: true, tenants: [{ id: "tenant", name: "Shop", role_code: "owner" }] });
    if (path === "/api/v1/integrations/whatsapp/embedded-signup/start") return json(route, { app_id: "123", config_id: "456", graph_version: "v26.0" });
    if (path === "/api/v1/integrations/whatsapp/embedded-signup/complete") {
      calls.push(JSON.parse(req.postData() || "{}"));
      return json(route, { id: "i1", provider: "whatsapp", status: "active", phone_number_id: "PN1", waba_id: "WB1" }, 201);
    }
    return json(route, []);
  });
  await page.goto("/settings/channels");
  return calls;
}

// The SDK stub answers FB.login with a code, and posts Meta's FINISH message before or after it.
// addInitScript serialises the function, so `order` must travel as its argument.
const sdkWith = (order) => {
  const finish = () =>
    window.dispatchEvent(
      new MessageEvent("message", {
        origin: "https://www.facebook.com",
        data: JSON.stringify({ type: "WA_EMBEDDED_SIGNUP", event: "FINISH", data: { waba_id: "WB1", phone_number_id: "PN1" } }),
      }),
    );
  window.FB = {
    init() {},
    login(cb) {
      if (order === "finish-first") {
        finish();
        setTimeout(() => cb({ authResponse: { code: "AUTHCODE12345" } }), 50);
      } else {
        cb({ authResponse: { code: "AUTHCODE12345" } });
        setTimeout(finish, 50);
      }
    },
  };
};

for (const order of ["finish-first", "code-first"]) {
  test(`WhatsApp connects when Meta sends the ${order.replace("-", " ")}`, async ({ page }) => {
    const calls = await open(page, { sdk: sdkWith, arg: order });
    await page.getByRole("button", { name: /^(Connect|ربط)$/ }).first().click();
    await expect.poll(() => calls.length, { timeout: 8000 }).toBe(1);
    expect(calls[0]).toEqual({ code: "AUTHCODE12345", waba_id: "WB1", phone_number_id: "PN1" });
    await expect(page.getByText(/WhatsApp number is connected|تم ربط رقم واتساب/).first()).toBeVisible();
  });
}

test("a cancelled WhatsApp popup is reported and nothing is sent", async ({ page }) => {
  const calls = await open(page, {
    sdk: () => {
      window.FB = {
        init() {},
        login() {
          window.dispatchEvent(
            new MessageEvent("message", { origin: "https://www.facebook.com", data: JSON.stringify({ type: "WA_EMBEDDED_SIGNUP", event: "CANCEL" }) }),
          );
        },
      };
    },
  });
  await page.getByRole("button", { name: /^(Connect|ربط)$/ }).first().click();
  await expect(page.getByText(/cancelled before it completed|أُلغيت عملية الربط/)).toBeVisible({ timeout: 8000 });
  expect(calls).toEqual([]);
});

test("a window message from another site cannot fake a Facebook connection", async ({ page }) => {
  await open(page, { sdk: () => { window.FB = { init() {}, login() {} }; } });
  await expect(page.getByRole("button", { name: /^(Connect|ربط)$/ }).first()).toBeVisible();
  await page.evaluate(() => {
    window.dispatchEvent(new MessageEvent("message", { origin: "https://evil.example", data: { type: "META_OAUTH_RESULT", connected: "1:Fake Page" } }));
  });
  await page.waitForTimeout(400);
  await expect(page.getByText(/Fake Page/)).toHaveCount(0);
});

test("the callback page's own message does show the connected Page", async ({ page }) => {
  await open(page, { sdk: () => { window.FB = { init() {}, login() {} }; } });
  await expect(page.getByRole("button", { name: /^(Connect|ربط)$/ }).first()).toBeVisible();
  await page.evaluate(() => {
    window.dispatchEvent(new MessageEvent("message", { origin: window.location.origin, data: { type: "META_OAUTH_RESULT", connected: "1:My Shop" } }));
  });
  await expect(page.getByText(/My Shop/).first()).toBeVisible({ timeout: 5000 });
});
