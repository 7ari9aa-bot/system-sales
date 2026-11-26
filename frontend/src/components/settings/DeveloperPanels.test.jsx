import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import ar from "@/lib/i18n/ar";
import en from "@/lib/i18n/en";
import { canSeeDevelopers, DEVELOPER_ROLES } from "@/lib/developerAccess";

const SECTION_20_PAGES = [
  "webhooks",
  "connected-apps",
  "rate-limits",
  "api-logs",
  "developer-environment",
];

describe("section 20 copy", () => {
  test("every live page has a title and a description in both languages", () => {
    for (const page of SECTION_20_PAGES) {
      for (const [lang, dict] of [
        ["ar", ar],
        ["en", en],
      ]) {
        for (const field of ["title", "desc"]) {
          const key = `settings.developers.pages.${page}.${field}`;
          expect(dict[key], `${lang} is missing ${key}`).toBeTruthy();
        }
      }
    }
  });

  test("the panels' labels exist in both languages", () => {
    const keys = [
      "settings.nav.developers",
      "settings.developers.title",
      "settings.developers.subtitle",
      "settings.developers.webhooks.title",
      "settings.developers.webhooks.desc",
      "settings.developers.webhooks.empty",
      "settings.developers.webhooks.active",
      "settings.developers.webhooks.inactive",
      "settings.developers.deliveries.title",
      "settings.developers.deliveries.desc",
      "settings.developers.deliveries.empty",
      "settings.developers.deliveries.attempts",
      "settings.developers.deliveries.whereToEdit",
      "settings.developers.rateLimits.title",
      "settings.developers.rateLimits.desc",
      "settings.developers.rateLimits.enforced",
      "settings.developers.rateLimits.on",
      "settings.developers.rateLimits.off",
      "settings.developers.rateLimits.window",
      "settings.developers.rateLimits.whereToEdit",
      "settings.developers.connectedApps.title",
      "settings.developers.connectedApps.desc",
      "settings.developers.connectedApps.body",
      "settings.developers.connectedApps.link",
      "settings.developers.environment.title",
      "settings.developers.environment.desc",
      "settings.developers.environment.origin",
      "settings.developers.environment.schema",
      "settings.developers.environment.body",
      "settings.developers.apiLogs.title",
      "settings.developers.apiLogs.desc",
      "settings.developers.apiLogs.empty",
      "settings.developers.apiLogs.whereToEdit",
    ];
    for (const key of keys) {
      expect(ar[key], `ar is missing ${key}`).toBeTruthy();
      expect(en[key], `en is missing ${key}`).toBeTruthy();
    }
  });

  test("every delivery status the API can return has a label", () => {
    for (const status of ["queued", "delivered", "failed", "dead"]) {
      for (const [lang, dict] of [
        ["ar", ar],
        ["en", en],
      ]) {
        const key = `settings.developers.deliveries.statuses.${status}`;
        expect(dict[key], `${lang} is missing ${key}`).toBeTruthy();
      }
    }
  });
});

describe("canSeeDevelopers", () => {
  const userWithRole = (role_code) => ({
    tenants: [{ id: "t1", name: "Shop", slug: "shop", role_code }],
  });

  test("the owner, admin and manager see the section", () => {
    for (const role of DEVELOPER_ROLES) {
      expect(canSeeDevelopers(userWithRole(role))).toBe(true);
    }
  });

  test("a cashier and a staff member do not", () => {
    expect(canSeeDevelopers(userWithRole("cashier"))).toBe(false);
    expect(canSeeDevelopers(userWithRole("staff"))).toBe(false);
  });

  test("no membership, or no role on it, is a no", () => {
    expect(canSeeDevelopers(null)).toBe(false);
    expect(canSeeDevelopers({})).toBe(false);
    expect(canSeeDevelopers({ tenants: [] })).toBe(false);
    expect(canSeeDevelopers(userWithRole(null))).toBe(false);
  });
});

describe("the role gate is on the route, not only in the sidebar", () => {
  test("the developers route is wrapped in DeveloperSectionGate", () => {
    const app = readFileSync(new URL("../../App.jsx", import.meta.url), "utf-8");
    const route = app.slice(app.indexOf('path="/settings/developers/:page"'));
    expect(route.slice(0, 400)).toContain("DeveloperSectionGate");
    expect(route.slice(0, 400)).toContain('section="developers"');
  });
});
