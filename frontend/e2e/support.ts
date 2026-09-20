import type { Page, Route } from "@playwright/test";

/** Shared E2E plumbing.
 *
 *  Every dashboard route sits behind the `Shell` guard, which redirects to
 *  `/auth/login` unless `sales_os_tokens` is present. Seeding that pair in an
 *  init script lets a spec land directly on a page without a backend, exactly
 *  as `dashboard.spec.ts` already does — this just factors the boilerplate out
 *  so each spec reads as assertions rather than setup.
 */

export const TEST_TOKENS = {
  access_token: "test-access-token",
  refresh_token: "test-refresh-token",
} as const;

export type Me = { id: string; email: string; tenants: { id: string }[] };

export const SHELL_ME: Me = {
  id: "user-1",
  email: "owner@example.com",
  tenants: [{ id: "tenant-1" }],
};

/** Seed the token pair the shell guard reads, before any navigation. */
export async function seedAuth(page: Page): Promise<void> {
  await page.addInitScript((tokens) => {
    window.localStorage.setItem("sales_os_tokens", JSON.stringify(tokens));
  }, TEST_TOKENS);
}

/** Pin the UI language. The app is Arabic-first and several labels are only
 *  reachable through the dictionary; pinning `en` keeps those assertions
 *  readable without hardcoding either translation. */
export async function seedLang(page: Page, lang: "ar" | "en"): Promise<void> {
  await page.addInitScript((value) => {
    window.localStorage.setItem("sales_os_lang", value);
  }, lang);
}

/** Fulfil a request with JSON and an explicit status. */
export function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, json: body });
}

/** A 500 carrying the error envelope the API client knows how to parse. */
export function serverError(route: Route, message = "upstream failure") {
  return route.fulfill({ status: 500, json: { error: { message } } });
}

/** Mock the chrome every dashboard page depends on: the user menu, the
 *  notification bell, the health badge, and the SSE stream (aborted so its
 *  backoff timer never races an assertion).
 *
 *  Register this first; Playwright matches the most recently registered route
 *  first, so a spec can override any single endpoint afterwards. */
export async function mockShell(page: Page, me: Me = SHELL_ME): Promise<void> {
  await page.route("**/api/v1/auth/me", (route) => json(route, me));

  await page.route("**/api/v1/notifications**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/unread-count")) return json(route, { count: 0 });
    if (path.endsWith("/summary")) return json(route, { total: 0, unread: 0, by_kind: [] });
    return json(route, []);
  });

  await page.route("**/api/v1/platform/health", (route) =>
    json(route, { status: "healthy", subsystems: [] }),
  );

  await page.route("**/api/v1/realtime/events*", (route) => route.abort());
}
