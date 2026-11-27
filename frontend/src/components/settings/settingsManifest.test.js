import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

import {
  ACCOUNT_PAGE_ITEMS,
  SETTINGS_PAGE_ROUTES,
  SETTINGS_GROUP_KEYS,
  SETTINGS_LEGACY_REDIRECTS,
  SETTINGS_NAV_GROUPS,
  SETTINGS_NAV_ROUTES,
  SETTINGS_SECTIONS,
  SETTINGS_UNLISTED_SCREENS,
  pageLink,
  pagePath,
  sectionBySlug,
  sectionPages,
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

/** The four components that render a section's inner navigation, read as text: the assertion is
 * about WHERE the page list comes from, which only the source can answer. */
const TAB_SOURCES = {
  SettingsSection: fs.readFileSync(path.resolve(__dirname, "../../pages/settings/SettingsSection.jsx"), "utf8"),
  WorkspaceSettings: fs.readFileSync(path.resolve(__dirname, "../../pages/settings/WorkspaceSettings.jsx"), "utf8"),
  TeamSettings: fs.readFileSync(path.resolve(__dirname, "../../pages/settings/TeamSettings.jsx"), "utf8"),
  ChannelSectionPage: fs.readFileSync(path.resolve(__dirname, "../../pages/settings/ChannelSectionPage.jsx"), "utf8"),
};

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

/**
 * The pages, not just the sections.
 *
 * The sidebar was unified first, and the review that followed found the section TABS still had
 * three separate definitions: `SettingsSection`'s own `SECTION_PAGES`, the two hand-built
 * wrappers, and the manifest. The four assertions below are the ones that would have caught it:
 * every declared page has a label in both languages, every declared page is a route the router
 * serves, every section's landing page is its own first page, and the tab strips are generated
 * from `sectionPages()` rather than from a list kept beside it.
 */
describe("settings manifest pages", () => {
  it("gives every page a label that exists in both languages", () => {
    const missing = [];
    for (const section of SETTINGS_SECTIONS) {
      if (section.id === "01") continue; // the account pages are sidebar items with their own keys
      for (const page of sectionPages(section.slug)) {
        if (!(page.labelKey in en) || !(page.labelKey in ar)) {
          missing.push(`${section.slug}/${page.slug} -> ${page.labelKey}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });

  it("only declares pages the router can serve", () => {
    const unserved = SETTINGS_PAGE_ROUTES.filter((to) => !isServed(to));
    expect(unserved).toEqual([]);
  });

  it("lands every section on its first page the Center actually configures", () => {
    // A landing is either the bare section address (workspace, channels and ai open their own
    // overview screen there) or the section's FIRST page. A landing on a middle page is the bug
    // this catches: four sections pointed at page three while their tab strip started at page one.
    //
    // A page that only hands over to a module (`links`) cannot be the landing: the section would
    // open on a card saying "this lives elsewhere" instead of on something to configure. So the
    // first CONFIGURED page is the landing.
    const wrong = SETTINGS_SECTIONS.filter((section) => section.id !== "01")
      .filter((section) => {
        const first = section.pages.find((page) => !pageLink(section, page));
        if (!first) return false;
        return section.to !== pagePath(section.slug, first) && section.to !== `/settings/${section.slug}`;
      })
      .map((section) => `${section.id} ${section.slug} -> ${section.to}`);
    expect(wrong).toEqual([]);
  });

  it("never lands a section on a page that only links away", () => {
    for (const section of SETTINGS_SECTIONS) {
      if (section.id === "01") continue;
      expect(pageLink(section, section.to.split("/").pop())).toBeNull();
    }
  });

  it("never lists the same page twice, and never reuses a label inside a section", () => {
    for (const section of SETTINGS_SECTIONS) {
      const pages = section.pages;
      expect(new Set(pages).size).toBe(pages.length);
      if (section.id === "01") continue;
      const keys = sectionPages(section.slug).map((page) => page.labelKey);
      expect(new Set(keys).size).toBe(keys.length);
    }
  });

  it("names the team matrix by the slug its route uses", () => {
    const team = sectionBySlug("team");
    expect(team.pages).toContain("matrix");
    expect(team.pages).not.toContain("permissions");
  });

  it("declares the AI section's nine real pages, not the four endpoint names", () => {
    const ai = sectionBySlug("ai");
    expect(ai.pages).toHaveLength(9);
    expect(ai.pages).toContain("agent-management");
    expect(ai.pages).toContain("versions-and-publishing");
    expect(ai.pages).not.toContain("agents");
  });

  it("gives the channel section the three pages that had routes but no entry", () => {
    const channels = sectionBySlug("channels");
    expect(channels.pages).toContain("data-sync");
    expect(channels.pages).toContain("external-integrations");
    expect(channels.pages).toContain("connection-health");
  });

  it("gives a pending page no tab, so no tab opens an empty screen", () => {
    const pending = ["export", "payment-methods", "renewal-and-upgrade", "api-keys"];
    for (const page of pending) {
      expect(SETTINGS_PAGE_ROUTES).not.toContain(`/settings/data/${page}`);
      expect(SETTINGS_PAGE_ROUTES).not.toContain(`/settings/billing/${page}`);
      expect(SETTINGS_PAGE_ROUTES).not.toContain(`/settings/developers/${page}`);
    }
  });

  it("builds every tab strip from the manifest, never from a list kept beside it", () => {
    for (const [name, source] of Object.entries(TAB_SOURCES)) {
      expect(source, `${name} must not keep its own page list`).not.toContain("SECTION_PAGES");
    }
    expect(TAB_SOURCES.SettingsSection).toContain("sectionPages(section)");
    expect(TAB_SOURCES.WorkspaceSettings).toContain('sectionPages("workspace")');
    expect(TAB_SOURCES.TeamSettings).toContain('sectionPages("team")');
    expect(TAB_SOURCES.ChannelSectionPage).toContain('section="channels"');
  });

  it("gives the two hand-built wrappers a screen for every page the manifest names", async () => {
    const workspace = await import("@/pages/settings/WorkspaceSettings");
    const team = await import("@/pages/settings/TeamSettings");
    expect([...workspace.WORKSPACE_SECTION_SLUGS].sort()).toEqual(
      sectionPages("workspace").map((page) => page.slug).sort()
    );
    expect([...team.TEAM_SECTION_SLUGS].sort()).toEqual(
      sectionPages("team").map((page) => page.slug).sort()
    );
  });
});
