import { expect, test, type Page } from "@playwright/test";
import { mockShell } from "./support";

/* F2 — a malformed token blob in localStorage.
 *
 *  `getTokens()` used to call `JSON.parse` bare. One truncated write (a tab
 *  killed mid-save, an extension editing the key, a user pasting into devtools)
 *  threw on the FIRST read every dashboard route makes, and it threw inside the
 *  shell guard — before anything had rendered. The whole dashboard went white on
 *  the strength of one byte.
 *
 *  The honest answer to unreadable credentials is "you are not signed in", which
 *  is exactly what the shell does with a null token pair: replace to /login. So
 *  each case below asserts three things — the app routed (it did not blank), the
 *  login card is on screen, and the page never threw an uncaught error.
 *
 *  `addInitScript` re-runs on a document load, not on the client-side
 *  `router.replace` this redirect uses, so the cleared-blob assertion at the
 *  bottom reads the storage of the same document that consumed the flag. */

const KEY = "sales_os_tokens";

async function seedRaw(page: Page, raw: string) {
  await page.addInitScript(
    ({ key, value }) => window.localStorage.setItem(key, value),
    { key: KEY, value: raw },
  );
}

const UNREADABLE: [string, string][] = [
  ["truncated JSON", '{"access_token":"a","refresh_token":"b"'],
  ["not JSON at all", "access-token-a"],
  ["JSON null", "null"],
  ["a bare number", "123"],
  ["an array", '[{"access_token":"a"}]'],
  ["no access token", '{"refresh_token":"b"}'],
];

for (const [label, raw] of UNREADABLE) {
  test(`unusable stored tokens (${label}) sign the user out instead of blanking the dashboard`, async ({
    page,
  }) => {
    const thrown: string[] = [];
    page.on("pageerror", (err) => thrown.push(String(err)));

    await seedRaw(page, raw);
    await mockShell(page);
    await page.goto("/dashboard");

    await expect(page).toHaveURL(/\/auth\/login$/);
    await expect(page.getByTestId("auth-login-card")).toBeVisible();
    expect(thrown).toEqual([]);
  });
}

test("the unreadable blob is removed, so the next load starts clean", async ({ page }) => {
  await seedRaw(page, "not json");
  await page.goto("/dashboard");

  await expect(page).toHaveURL(/\/auth\/login$/);
  const stored = await page.evaluate((key) => window.localStorage.getItem(key), KEY);
  expect(stored).toBeNull();
});

test("readable stored tokens still authenticate the shell", async ({ page }) => {
  await seedRaw(page, JSON.stringify({ access_token: "a", refresh_token: "b" }));
  await mockShell(page);
  await page.route("**/api/v1/tasks**", (route) => route.fulfill({ status: 200, json: [] }));

  await page.goto("/tasks");

  await expect(page.getByTestId("nav-tasks")).toBeVisible();
});
