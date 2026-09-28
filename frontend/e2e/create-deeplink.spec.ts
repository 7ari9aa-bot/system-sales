import { expect, test, type Page } from "@playwright/test";
import { json, mockShell, seedAuth } from "./support";

/* F14 — `?new=1` opens a create surface and must then leave the URL alone.
 *
 *  The top-bar «إنشاء» menu and the command palette both navigate to
 *  `/route?new=1`. Every page read the flag and opened its dialog, and none of
 *  them removed it — so a merchant who refreshed got an empty create dialog
 *  reopened over a page they were already reading, and the flag kept replaying
 *  from the history entry.
 *
 *  Each case: land on the deep link, see the surface open, see the flag gone
 *  from the URL, then RELOAD and see it stayed shut. The reload is the claim.
 *  `landmark` is asserted after the reload because `toHaveCount(0)` on a dialog
 *  passes trivially against a page that never hydrated — the landmark proves the
 *  shell AND the route body came back before we read the absence.
 *
 *  Settings is the odd one: it has no create dialog, so its deep link focuses the
 *  invite field. Same stale flag, same consumption, so it rides along. */

type DeepLink = {
  path: string;
  /** Rendered only by the route body — proves the page came back after reload. */
  landmark: string;
  /** `dialog` = Radix modal, `invite-field` = settings' focused input. */
  surface: "dialog" | "invite-field";
  routes: [string, unknown][];
};

const DEEP_LINKS: DeepLink[] = [
  {
    path: "/orders",
    landmark: '[data-testid="toggle-order-form"]',
    surface: "dialog",
    routes: [
      ["**/api/v1/orders**", { items: [] }],
      ["**/api/v1/customers**", { items: [] }],
    ],
  },
  {
    path: "/products",
    landmark: '[data-testid="open-product-form"]',
    surface: "dialog",
    routes: [["**/api/v1/products**", []]],
  },
  {
    path: "/marketing",
    landmark: '[data-testid="open-campaign-form"]',
    surface: "dialog",
    routes: [
      ["**/api/v1/marketing/campaigns**", { items: [] }],
      ["**/api/v1/analytics/summary**", {}],
    ],
  },
  {
    path: "/ai",
    landmark: '[data-testid="open-knowledge-form"]',
    surface: "dialog",
    routes: [
      ["**/api/v1/ai/knowledge**", { items: [] }],
      ["**/api/v1/ai/agents**", []],
      [
        "**/api/v1/ai/usage/summary**",
        { summary: [], totals: { cost: "0.0000", tokens_in: 0, tokens_out: 0 } },
      ],
    ],
  },
  {
    path: "/settings",
    landmark: "#inv-email",
    surface: "invite-field",
    routes: [
      ["**/api/v1/invitations**", []],
      ["**/api/v1/integrations**", []],
    ],
  },
];

async function seed(page: Page, entry: DeepLink) {
  await seedAuth(page);
  await mockShell(page);
  await page.route("**/api/v1/tenants/*/currency", (route) =>
    json(route, { tenant_id: "tenant-1", currency: "EGP" }),
  );
  for (const [pattern, body] of entry.routes) {
    await page.route(pattern, (route) => json(route, body));
  }
}

const focusedId = (page: Page) => page.evaluate(() => document.activeElement?.id ?? "");

/** The deep link did its job. Settings has no dialog to appear, so its evidence
 *  is the focus the link moved onto the invite field — asserting the field is
 *  merely VISIBLE would prove nothing, since the page renders it anyway. */
async function expectOpened(page: Page, entry: DeepLink) {
  if (entry.surface === "dialog") await expect(page.getByRole("dialog")).toBeVisible();
  else await expect.poll(() => focusedId(page)).toBe("inv-email");
}

/** ...and a reload does not undo it. */
async function expectClosed(page: Page, entry: DeepLink) {
  if (entry.surface === "dialog") await expect(page.getByRole("dialog")).toHaveCount(0);
  else expect(await focusedId(page)).not.toBe("inv-email");
}

/** The URL a consumed deep link leaves behind.
 *
 *  `toHaveURL` given a REGEXP matches it against the ABSOLUTE href
 *  (`http://127.0.0.1:3000/orders`), so an anchored `^/orders$` could never
 *  match — it rejected every route on every attempt while the app was already
 *  behaving. Given a STRING, Playwright resolves it against `baseURL` and
 *  compares the whole URL for equality, which is both what this contract says
 *  (path, and nothing after it) and stricter than the regex it replaces: no
 *  prefix, no query, no trailing segment survives it. */
const cleanUrl = (entry: DeepLink) => entry.path;

for (const entry of DEEP_LINKS) {
  test(`${entry.path}?new=1 opens its create surface and drops the flag from the URL`, async ({
    page,
  }) => {
    await seed(page, entry);

    await page.goto(`${entry.path}?new=1`);

    await expectOpened(page, entry);
    await expect(page).toHaveURL(cleanUrl(entry));
  });

  test(`${entry.path}: refreshing after the deep link leaves the create surface closed`, async ({
    page,
  }) => {
    await seed(page, entry);

    await page.goto(`${entry.path}?new=1`);
    await expectOpened(page, entry);
    // The flag is deleted by a `router.replace` that lands some frames after the
    // surface opens. Reloading before it lands reloads `?new=1` itself, which
    // re-fires the deep link — and the absence asserted below would then be
    // testing a page that was never asked to stay shut. Wait for the consumed
    // URL first, so the reload is the only thing under test.
    await expect(page).toHaveURL(cleanUrl(entry));

    await page.reload();

    await expect(page.locator(entry.landmark)).toBeVisible();
    await expectClosed(page, entry);
  });
}

test("a dialog closed by hand stays closed across a refresh", async ({ page }) => {
  await seed(page, DEEP_LINKS[1]);

  await page.goto("/products?new=1");
  await expect(page.getByRole("dialog")).toBeVisible();

  await page.getByRole("button", { name: "إلغاء" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.reload();
  await expect(page.locator('[data-testid="open-product-form"]')).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
