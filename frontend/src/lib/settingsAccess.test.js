import { describe, expect, it } from "vitest";
import {
  canSeeSection,
  canWriteSettings,
  visibleNavGroups,
  SETTINGS_READ,
  SETTINGS_WRITE,
} from "@/lib/settingsAccess";
import {
  ACCOUNT_PAGE_ITEMS,
  SETTINGS_NAV_GROUPS,
  sectionByPath,
  sectionBySlug,
} from "@/components/settings/settingsManifest";

/**
 * The grant, not the role name.
 *
 * The seeded matrix (scripts/provision.py ROLE_MATRIX) is the fact these tests stand on:
 * `staff` holds no `settings:*` code at all and `manager` holds `settings:read` but not
 * `settings:write`. Deciding from the role NAME is what offered twenty sections to staff and
 * let a manager type into a field the save refuses.
 */
const access = (roleCode, codes) => ({ roleCode, permissions: new Set(codes) });

const STAFF = access("staff", ["customers:read", "orders:read"]);
const MANAGER = access("manager", [SETTINGS_READ, "settings:branch_write"]);
const OWNER = access("owner", [SETTINGS_READ, SETTINGS_WRITE]);

describe("settings access", () => {
  it("hides every shop section from a member with no settings code", () => {
    for (const slug of ["store", "team", "channels", "ai", "security", "billing", "developers"]) {
      expect(canSeeSection(STAFF, sectionBySlug(slug))).toBe(false);
    }
  });

  it("still shows the person their own account pages", () => {
    // A staff member changes their own password with no settings grant at all.
    expect(canSeeSection(STAFF, sectionBySlug("profile"))).toBe(true);
    for (const item of ACCOUNT_PAGE_ITEMS) {
      expect(canSeeSection(STAFF, item)).toBe(true);
    }
  });

  it("shows the shop to a manager who may read but not write", () => {
    expect(canSeeSection(MANAGER, sectionBySlug("store"))).toBe(true);
    expect(canWriteSettings(MANAGER)).toBe(false);
    expect(canWriteSettings(OWNER)).toBe(true);
  });

  it("keeps the developer section's role gate on top of the grant", () => {
    // Section 20 asks for a role, not only a code: an owner who is a developer sees it, a
    // staff member does not, and the two rules must both hold.
    const developers = sectionBySlug("developers");
    expect(canSeeSection(OWNER, developers)).toBe(true);
    expect(canSeeSection(access("admin", [SETTINGS_READ, SETTINGS_WRITE]), developers)).toBe(true);
    expect(canSeeSection({ roleCode: "staff", permissions: new Set([SETTINGS_READ]) }, developers)).toBe(false);
  });

  it("answers null while the grant is unknown instead of guessing", () => {
    expect(canSeeSection(null, sectionBySlug("store"))).toBeNull();
    expect(canWriteSettings(null)).toBeNull();
  });
});

describe("sectionByPath", () => {
  it("puts the personal screens first, because three of them share a section's slug", () => {
    // The trap: /settings/security is the person's own password screen, while
    // /settings/security/audit-log is section 18. A slug-prefix match alone denies a staff
    // member their own screen.
    expect(sectionByPath("/settings/security")?.id).toBe("01");
    expect(sectionByPath("/settings/security/audit-log")?.id).toBe("18");
    expect(sectionByPath("/settings/notifications")?.id).toBe("01");
    expect(sectionByPath("/settings/notifications/notification-channels")?.id).toBe("16");
    expect(sectionByPath("/settings")?.id).toBe("01");
  });

  it("resolves a section from its landing and its pages", () => {
    expect(sectionByPath("/settings/store")?.id).toBe("04");
    expect(sectionByPath("/settings/store/business-profile")?.id).toBe("04");
    expect(sectionByPath("/settings/workspace/data")?.id).toBe("02");
    expect(sectionByPath("/settings/data/import")?.id).toBe("17");
    expect(sectionByPath("/settings/channels/data-sync")?.id).toBe("12");
  });

  it("answers null for an address outside the Center", () => {
    expect(sectionByPath("/dashboard")).toBeNull();
  });
});

describe("the sidebar under a grant", () => {
  const groups = SETTINGS_NAV_GROUPS;

  it("offers a staff member their account and nothing else", () => {
    const visible = visibleNavGroups(groups, (item) => canSeeSection(STAFF, item));
    const routes = visible.flatMap((group) => group.items.map((item) => item.to));
    expect(routes).toEqual([
      "/settings",
      "/settings/login",
      "/settings/security",
      "/settings/preferences",
      "/settings/notifications",
    ]);
    // ...and no empty group headings are left behind.
    expect(visible).toHaveLength(1);
  });

  it("offers a manager every shop section, because read is not write", () => {
    const visible = visibleNavGroups(groups, (item) => canSeeSection(MANAGER, item));
    const routes = visible.flatMap((group) => group.items.map((item) => item.to));
    // Sections link to their LANDING page, so the assertion is a prefix.
    expect(routes.some((to) => to.startsWith("/settings/store"))).toBe(true);
    expect(routes.some((to) => to.startsWith("/settings/team"))).toBe(true);
    expect(routes.some((to) => to.startsWith("/settings/security"))).toBe(true);
  });

  it("shows nothing decided while the grant is still loading", () => {
    const visible = visibleNavGroups(groups, (item) => canSeeSection(null, item));
    expect(visible.flatMap((group) => group.items)).toHaveLength(
      groups.flatMap((group) => group.items).length
    );
  });
});
