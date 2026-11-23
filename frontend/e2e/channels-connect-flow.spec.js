import { expect, test } from "@playwright/test";

// The connect flows on Settings > Channels, end to end with only HTTP and Meta's SDK faked:
// WhatsApp's popup hands back a code AND, separately, a window message with the ids, in either
// order; and the Meta OAuth result banner must only trust our own page.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const json = (route, data, status = 200) => route.fulfill({ status, json: data });


// Meta's signup messages arrive from the popup window, which is a separate browsing context, so
// the page only trusts a message that carries a source other than itself (W11). A stub that
// dispatches a bare MessageEvent has no source and is therefore ignored, which is not what Meta
// does; this helper posts from a throwaway same-origin frame so the event looks like the popup's.
const postFromPopup = () => {
  window.__postMetaSignup = (data) => {
    const frame = document.createElement("iframe");
    frame.hidden = true;
    document.documentElement.appendChild(frame);
    const source = frame.contentWindow;
    window.dispatchEvent(
      new MessageEvent("message", { origin: "https://www.facebook.com", data: JSON.stringify(data), source }),
    );
    frame.remove();
  };
};

async function open(page, { sdk, arg }) {
  const calls = [];
  await page.addInitScript(postFromPopup);
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
    window.__postMetaSignup({ type: "WA_EMBEDDED_SIGNUP", event: "FINISH", data: { waba_id: "WB1", phone_number_id: "PN1" } });
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

test("a code that outlives the wait for the signup report is not sent, and the owner is told why", async ({ page }) => {
  // The code arrives but Meta's window never reports the new number. Meta's code lives about five
  // minutes; the connect used to wait ten and then send a dead one, so the owner heard "Meta
  // rejected the authorization code" about a number that had in fact been created.
  await page.clock.install();
  const calls = await open(page, {
    sdk: () => {
      window.FB = {
        init() {},
        login(cb) {
          cb({ authResponse: { code: "AUTHCODE12345" } });
        },
      };
    },
  });
  await page.getByRole("button", { name: /^(Connect|ربط)$/ }).first().click();
  await page.clock.fastForward(4 * 60 * 1000 + 5000);
  await expect(page.getByText(/authorization expired before the steps|انتهت صلاحية رمز التفويض/)).toBeVisible({ timeout: 8000 });
  expect(calls).toEqual([]);
});

test("a report that arrives within the wait still connects, however late", async ({ page }) => {
  await page.clock.install();
  const calls = await open(page, {
    sdk: () => {
      window.FB = {
        init() {},
        login(cb) {
          cb({ authResponse: { code: "AUTHCODE12345" } });
          setTimeout(
            () => window.__postMetaSignup({ type: "WA_EMBEDDED_SIGNUP", event: "FINISH", data: { waba_id: "WB1", phone_number_id: "PN1" } }),
            3 * 60 * 1000,
          );
        },
      };
    },
  });
  await page.getByRole("button", { name: /^(Connect|ربط)$/ }).first().click();
  await page.clock.fastForward(3 * 60 * 1000 + 1000);
  await expect.poll(() => calls.length, { timeout: 8000 }).toBe(1);
  expect(calls[0]).toEqual({ code: "AUTHCODE12345", waba_id: "WB1", phone_number_id: "PN1" });
});

test("a cancelled WhatsApp popup is reported and nothing is sent", async ({ page }) => {
  const calls = await open(page, {
    sdk: () => {
      window.FB = {
        init() {},
        login() {
          window.__postMetaSignup({ type: "WA_EMBEDDED_SIGNUP", event: "CANCEL" });
        },
      };
    },
  });
  await page.getByRole("button", { name: /^(Connect|ربط)$/ }).first().click();
  await expect(page.getByText(/signup window was closed before it finished|أُغلقت نافذة الربط قبل اكتمالها/)).toBeVisible({ timeout: 8000 });
  expect(calls).toEqual([]);
});

test("a cancel names the step the owner left on", async ({ page }) => {
  const calls = await open(page, {
    sdk: () => {
      window.FB = {
        init() {},
        login() {
          window.__postMetaSignup({ type: "WA_EMBEDDED_SIGNUP", event: "CANCEL", data: { current_step: "PHONE_NUMBER_SETUP" } });
        },
      };
    },
  });
  await page.getByRole("button", { name: /^(Connect|ربط)$/ }).first().click();
  await expect(page.getByText(/PHONE_NUMBER_SETUP/)).toBeVisible({ timeout: 8000 });
  expect(calls).toEqual([]);
});

test("an error from Meta shows Meta's own reason and ids, not 'cancelled'", async ({ page }) => {
  const calls = await open(page, {
    sdk: () => {
      window.FB = {
        init() {},
        login() {
          window.__postMetaSignup({
            type: "WA_EMBEDDED_SIGNUP",
            event: "ERROR",
            data: { error_message: "Phone number is blocked", error_id: "1234", session_id: "s-9" },
          });
        },
      };
    },
  });
  await page.getByRole("button", { name: /^(Connect|ربط)$/ }).first().click();
  const shown = page.getByText(/Phone number is blocked/);
  await expect(shown).toBeVisible({ timeout: 8000 });
  await expect(shown).toContainText("1234");
  await expect(shown).toContainText("s-9");
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

test("a Meta-looking signup message with no source is not trusted", async ({ page }) => {
  // Only the popup can send the signup result. An event with no source did not come from another
  // browsing context, so it must not send the owner's code to the server.
  const calls = await open(page, {
    sdk: () => {
      window.FB = {
        init() {},
        login(cb) {
          cb({ authResponse: { code: "AUTHCODE12345" } });
          window.dispatchEvent(
            new MessageEvent("message", {
              origin: "https://www.facebook.com",
              data: JSON.stringify({ type: "WA_EMBEDDED_SIGNUP", event: "FINISH", data: { waba_id: "WB1", phone_number_id: "PN1" } }),
            }),
          );
        },
      };
    },
  });
  await page.getByRole("button", { name: /^(Connect|ربط)$/ }).first().click();
  await page.waitForTimeout(2000);
  expect(calls).toEqual([]);
  await expect(page.getByText(/WhatsApp number is connected|تم ربط رقم واتساب/)).toHaveCount(0);
});
