import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

import {
  ACCOUNT_PAGE_ITEMS,
  SETTINGS_GROUP_KEYS,
  SETTINGS_LEGACY_REDIRECTS,
  SETTINGS_NAV_GROUPS,
  SETTINGS_NAV_ROUTES,
  SETTINGS_SECTIONS,
  SETTINGS_UNLISTED_SCREENS,
} from "@/components/settings/settingsManifest";
import en from "@/lib/i18n/en";
import ar from "@/lib/i18n/ar";

/**
 * The manifest is the one place that says what the Settings Center holds, so it is the one
 * place a drift can be caught cheaply. Each assertion below corresponds to a way the Center
 * has ALREADY drifted once:
 *
 *   - a section in the router that the sidebar never showed (team, customers, analytics,
 *     automation, workspace notifications, data) — caught by the route/label checks;
 *   - two addresses editing the same rows (`/settings/members` vs `/settings/team/*`);
 *   - a label added in one language only, which renders as a raw key in the other.
 */
const APP_SOURCE = fs.readFileSync(path.resolve(__dirname, "../../App.jsx"), "utf8");

/** Every path the router registers, with `:param` segments kept as wildcards. */
const ROUTE_PATTERNS = [...APP_SOURCE.matchAll(/<Route\s+path="([^"]+)"/g)].map((match) =>
  match[1]
);

function isServed(to) {
  const target = to.replace(/\/$/, "") || "/";
  return ROUTE_PATTERNS.some((pattern) => {
    // `*` is the catch-all: it serves anything, so it proves nothing about a specific address.
    if (pattern === "*") return false;
    const escaped = pattern
      .replace(/[.*+?^${}()|[\]\\]/g, (char) => (char === ":" ? char : `\\${char}`))
      .replace(/:\w+/g, "[^/]+");
    return new RegExp(`^${escaped}$`).test(target);
  });
}

describe("settings manifest", () => {
  it("holds the map's five groups and twenty sections", () => {
    expect(SETTINGS_GROUP_KEYS).toHaveLength(5);
    expect(SETTINGS_NAV_GROUPS).toHaveLength(5);
    expect(SETTINGS_SECTIONS).toHaveLength(20);
    expect(SETTINGS_SECTIONS.map((section) => section.id)).toEqual(
      Array.from({ length: 20 }, (_, index) => String(index + 1).padStart(2, "0"))
    );
  });

  it("never links two sections to the same address", () => {
    const routes = SETTINGS_NAV_ROUTES;
    expect(new Set(routes).size).toBe(routes.length);
  });

  it("only links to addresses the router actually serves", () => {
    const unserved = SETTINGS_NAV_ROUTES.filter((to) => !isServed(to));
    expect(unserved).toEqual([]);
  });

  it("points the team section at the six real pages, not the old combined screen", () => {
    const team = SETTINGS_SECTIONS.find((section) => section.id === "03");
    expect(team.to).toBe("/settings/team/members");
    expect(team.pages).toHaveLength(6);
    expect(SETTINGS_NAV_ROUTES).not.toContain("/settings/members");
  });

  it("forwards the legacy team address instead of dropping it", () => {
    const legacy = SETTINGS_LEGACY_REDIRECTS.find((entry) => entry.from === "/settings/members");
    expect(legacy).toBeDefined();
    expect(isServed(legacy.to)).toBe(true);
    expect(SETTINGS_NAV_ROUTES).toContain(legacy.to);
  });

  it("keeps the unlisted screens reachable by address and says why each is unlisted", () => {
    for (const screen of SETTINGS_UNLISTED_SCREENS) {
      expect(isServed(screen.to)).toBe(true);
      expect(SETTINGS_NAV_ROUTES).not.toContain(screen.to);
      expect(screen.why.length).toBeGreaterThan(40);
    }
  });

  it("hides exactly one section by role, and it is the developers section", () => {
    const gated = SETTINGS_SECTIONS.filter((section) => section.roles);
    expect(gated.map((section) => section.id)).toEqual(["20"]);
  });

  it("gives every entry a label in both languages", () => {
    const labelKeys = [
      ...SETTINGS_GROUP_KEYS,
      ...ACCOUNT_PAGE_ITEMS.map((item) => item.labelKey),
      ...SETTINGS_SECTIONS.map((section) => section.labelKey),
    ];
    const missing = labelKeys.filter((key) => !(key in en) || !(key in ar));
    expect(missing).toEqual([]);
  });

  it("gives every entry an icon and a section id where it is a section", () => {
    for (const section of SETTINGS_SECTIONS) {
      expect(section.icon).toBeTruthy();
      expect(section.pages.length).toBeGreaterThan(0);
    }
  });
});
