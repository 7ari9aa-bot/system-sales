import { expect, test } from "@playwright/test";

// The audit's findings, pinned as behaviour. Four pages changed because each one was answering a
// question it did not own: Members apologised for a roster it could already read, Billing printed
// the same token totals as Usage, Security opened with three "the API cannot tell you" notes while
// the account already carried the answer, and "Danger zone" held no dangerous action at all.
const json = (route, data, status = 200) => route.fulfill({ status, json: data });

async function setup(page, { lifecycle = "active", mfa = false, lang = "en" } = {}) {
  const state = {
    mfa,
    members: [
      { id: "user", email: "owner@example.com", full_name: "Merchant One", role_code: "owner" },
      { id: "u2", email: "sara@example.com", full_name: "Sara Two", role_code: "manager" },
    ],
    invitations: [
      { id: "inv1", email: "new@example.com", role_code: "staff", status: "pending" },
      { id: "inv2", email: "old@example.com", role_code: "staff", status: "accepted" },
    ],
    resetRequests: [],
    exports: 0,
  };
  await page.context().addCookies([
    { name: "csrf_token", value: "ui-test", url: new URL(process.env.BASE_URL || "http://127.0.0.1:4173").origin },
  ]);
  await page.addInitScript((locale) => localStorage.setItem("salesos.lang", locale), lang);
  const me = () => ({
    id: "user",
    email: "owner@example.com",
    full_name: "Merchant One",
    avatar_url: null,
    is_platform_admin: false,
    mfa_enabled: state.mfa,
    tenants: [{ id: "tenant", name: "Shop", slug: "shop-1", role_code: "owner" }],
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path === "/api/v1/auth/me") return json(route, me());
    if (path === "/api/v1/users") return json(route, state.members);
    if (path === "/api/v1/invitations" && request.method() === "GET") return json(route, state.invitations);
    if (path === "/api/v1/billing/subscription") {
      return json(route, { status: "trialing", current_period_end: "2026-12-01T00:00:00Z" });
    }
    if (path === "/api/v1/ai/usage/summary") {
      return json(route, { totals: { tokens_in: 1200, tokens_out: 800, cost: 1.5 }, days: 14, summary: [] });
    }
    if (path === "/api/v1/auth/mfa/enroll") {
      return json(route, { secret: "JBSWY3DPEHPK3PXP", otpauth_url: "otpauth://totp/x?secret=JBSWY3DPEHPK3PXP" }, 201);
    }
    if (path === "/api/v1/auth/mfa/confirm") {
      state.mfa = true;
      return json(route, { backup_codes: ["aaaa1111bbbb2222", "cccc3333dddd4444"] });
    }
    if (path === "/api/v1/auth/mfa/disable") {
      state.mfa = false;
      return route.fulfill({ status: 204, body: "" });
    }
    if (path === "/api/v1/auth/password-reset/request") {
      state.resetRequests.push(request.postDataJSON());
      return json(route, { message: "If the account exists, password reset instructions will be sent shortly." }, 202);
    }
    if (path === "/api/v1/tenants/tenant/lifecycle") {
      return json(route, {
        lifecycle_state: lifecycle,
        deletion_scheduled_at: lifecycle === "offboarding" ? "2026-12-15T00:00:00Z" : null,
      });
    }
    if (path === "/api/v1/tenants/tenant/offboarding/export") {
      state.exports += 1;
      return json(route, { tenant: { id: "tenant", name: "Shop" }, records: [] });
    }
    if (path === "/api/v1/ai/agents" || path === "/api/v1/ai/agent-kinds") return json(route, []);
    return json(route, {});
  });
  return state;
}

test("members shows the real roster and the invitations still waiting", async ({ page }) => {
  await setup(page);
  await page.goto("/settings/members");

  const roster = page.getByTestId("members-table");
  await expect(roster.getByText("Merchant One")).toBeVisible();
  await expect(roster.getByText("Sara Two")).toBeVisible();
  await expect(roster.getByText("sara@example.com")).toBeVisible();
  // the signed-in owner is marked as such
  await expect(roster.getByText("you", { exact: true })).toBeVisible();

  // the pending invite sits beside the members; the accepted one is not "waiting"
  await expect(page.getByTestId("invitation-row")).toHaveCount(1);
  await expect(page.getByTestId("invitation-row").getByText("new@example.com")).toBeVisible();
  await expect(roster.getByText("old@example.com")).toHaveCount(0);

  // and the apology that the roster is unavailable is gone
  await expect(page.getByText(/does not expose the full workspace member roster/i)).toHaveCount(0);
});

test("billing is money only and points at usage instead of repeating it", async ({ page }) => {
  await setup(page);
  // section 19 owns the plan: the old single billing screen now lands on its first page
  await page.goto("/settings/billing");
  await expect(page).toHaveURL(/\/settings\/billing\/current-plan$/);

  // the real subscription row: status and the period it actually ends
  const plan = page.locator("section").filter({ has: page.getByRole("heading", { name: "Subscription and plan", exact: true }) });
  await expect(plan.getByText("Trialing")).toBeVisible();
  await expect(plan.getByText("1 Dec 2026")).toBeVisible();

  // the token totals belong to Usage; nothing on this page may print them
  await expect(page.getByText("Token usage")).toHaveCount(0);
  await expect(page.getByText("2,000")).toHaveCount(0);
  // no upgrade button that would do nothing: the page says why there is none
  await expect(page.getByText(/no payment provider is configured/i)).toBeVisible();

  await page.getByRole("link", { name: "Usage", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/billing\/usage$/);
  // ...and this usage page counts plan limits, not the AI token totals the usage screen owns
  await expect(page.getByText(/same service that refuses a request past its limit/i)).toBeVisible();
  await expect(page.getByText("2,000")).toHaveCount(0);
});

test("security reads the real two-step state instead of apologising for it", async ({ page }) => {
  await setup(page, { mfa: false });
  await page.goto("/settings/security");

  await expect(page.getByTestId("mfa-status")).toHaveText("Off");
  await expect(page.getByText(/does not expose the existing MFA status/i)).toHaveCount(0);

  // set it up end to end: password -> secret -> code -> On
  await page.getByLabel(/Account password to start setup/i).fill("hunter2hunter2");
  await page.getByRole("button", { name: "Set up two-step verification" }).click();
  await expect(page.getByText("JBSWY3DPEHPK3PXP")).toBeVisible();
  await page.getByLabel(/6-digit verification code/i).fill("123456");
  await page.getByRole("button", { name: "Confirm and enable" }).click();

  await expect(page.getByText("aaaa1111bbbb2222")).toBeVisible();
  await expect(page.getByTestId("mfa-status")).toHaveText("On");
});

test("login can send a password reset link and never claims the mail arrived", async ({ page }) => {
  const state = await setup(page);
  // recovery is a sign-in concern, so it lives on the sign-in page, not on the security screen
  await page.goto("/settings/login");

  await page.getByTestId("login-reset-link").click();

  await expect(page.getByTestId("login-reset-notice")).toContainText("If owner@example.com is a known account");
  expect(state.resetRequests).toEqual([{ email: "owner@example.com" }]);
  await expect(page.getByText(/delivered|sent to your inbox/i)).toHaveCount(0);
});

test("the data page names itself honestly and explains why export is closed", async ({ page }) => {
  await setup(page, { lifecycle: "active" });
  await page.goto("/settings/danger");

  await expect(page.getByRole("heading", { level: 1, name: "Data & offboarding" })).toBeVisible();
  await expect(page.getByTestId("workspace-state")).toHaveText("active");
  await expect(page.getByTestId("data-export")).toBeDisabled();
  await expect(page.getByTestId("data-export-reason")).toContainText("during the offboarding window");
  // the nav item says the same thing as the page it opens
  await expect(page.getByRole("navigation").getByRole("link", { name: "Data & offboarding" })).toBeVisible();
});

test("during offboarding the export button actually works", async ({ page }) => {
  const state = await setup(page, { lifecycle: "offboarding" });
  await page.goto("/settings/danger");

  await expect(page.getByTestId("data-export")).toBeEnabled();
  await expect(page.getByTestId("data-export-reason")).toHaveCount(0);
  await page.getByTestId("data-export").click();
  await expect.poll(() => state.exports).toBe(1);
});

test("Arabic: the four pages speak Arabic too", async ({ page }) => {
  await setup(page, { lang: "ar" });

  await page.goto("/settings/security");
  await expect(page.getByRole("heading", { level: 1, name: "تسجيل الدخول والأمان" })).toBeVisible();
  await expect(page.getByTestId("mfa-status")).toHaveText("مقفولة");

  await page.goto("/settings/danger");
  await expect(page.getByRole("heading", { level: 1, name: "البيانات والإنهاء" })).toBeVisible();
  await expect(page.getByTestId("data-export")).toContainText("تنزيل");
});

test("mobile: the four pages fit 390px without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);

  const anchors = [
    ["/settings/members", "members-table"],
    ["/settings/billing/current-plan", null],
    ["/settings/security", "mfa-status"],
    ["/settings/danger", "workspace-state"],
  ];
  for (const [path, anchor] of anchors) {
    await page.goto(path);
    if (anchor) await page.getByTestId(anchor).waitFor();
    else await page.getByRole("heading", { level: 1 }).first().waitFor();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${path} must fit 390px`).toBeLessThanOrEqual(1);
  }
});
