import { expect, test } from "@playwright/test";

// When Meta's own dialog refuses ("App not active") it closes with no authorization code. The old
// message only said "no code, try again", which sent the shop owner in circles over a problem that
// lives in the Meta developer console. Only HTTP and the Facebook SDK are faked here.
const json = (route, data, status = 200) => route.fulfill({ status, json: data });

async function openAndConnect(page) {
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(process.env.BASE_URL || "http://127.0.0.1:4173").origin }]);
  await page.addInitScript(() => {
    // The SDK the page would download: init is a no-op and login answers with no authResponse.
    window.FB = { init() {}, login: (cb) => cb({ status: "unknown" }) };
  });
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/auth/me") return json(route, { id: "u", email: "t@e.com", full_name: "T", is_active: true, tenants: [{ id: "tenant", name: "Shop", role_code: "owner" }] });
    if (path === "/api/v1/integrations/whatsapp/embedded-signup/start") return json(route, { app_id: "123", config_id: "456", graph_version: "v26.0" });
    return json(route, []);
  });
  await page.goto("/settings/channels");
  // The Facebook SDK path belongs to WhatsApp alone. Pressing the first Connect on the page
  // pressed whichever channel now leads the list, and its popup reported a different error
  // ("The server returned no authorize URL"), so this test never reached the message it guards.
  await page
    .getByTestId("channel-whatsapp")
    .getByRole("button", { name: /^(Connect|ربط)$/ })
    .first()
    .click();
  return page.getByText(/App not active/).first();
}

test("a Facebook window that closes without a code names the likely cause: the Meta app is switched off", async ({ page }) => {
  const alert = await openAndConnect(page);
  await expect(alert).toBeVisible({ timeout: 8000 });
  // The wording moved when the WhatsApp connect started explaining Meta-side refusals (12b58b82).
  await expect(alert).toContainText(/window closed before the connect finished/i);
  await expect(alert).toContainText(/the app is switched off/i);
});
