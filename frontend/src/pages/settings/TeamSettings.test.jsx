/**
 * The team section: six pages, and the boundaries that make them safe.
 *
 * The promises worth pinning are not cosmetic. Roles and the matrix are read-only
 * because a writable matrix would be a second permission system the API guards do
 * not know about. Teams are groupings, so the page says so instead of letting people
 * assume a team grants. Access scope is about branches only. And the roster page is
 * the same implementation as /settings/members with a different view, so there is
 * one table to maintain rather than two that drift.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import TeamSettings, { TEAM_SECTION_SLUGS, resolveTeamSection } from "./TeamSettings";

vi.mock("@/lib/api", () => ({
  api: vi.fn(() => Promise.resolve(null)),
}));

vi.mock("@/lib/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      tenant_id: "t1",
      tenants: [{ id: "t1", name: "Cairo Shop", slug: "cairo-shop", role_code: "owner" }],
    },
    refreshUser: vi.fn(),
  }),
}));

const render = (path = "/settings/team") =>
  renderToStaticMarkup(
    <I18nProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/settings/team" element={<TeamSettings />} />
          <Route path="/settings/team/:section" element={<TeamSettings />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>
  );

describe("TeamSettings", () => {
  test("the six pages of the map each have a route", () => {
    expect(TEAM_SECTION_SLUGS).toEqual([
      "members",
      "invitations",
      "roles",
      "matrix",
      "groups",
      "access",
    ]);
  });

  test("an unknown section falls back to the roster", () => {
    expect(resolveTeamSection(undefined).value).toBe("members");
    expect(resolveTeamSection("nope").value).toBe("members");
    expect(resolveTeamSection("matrix").value).toBe("matrix");
  });

  test("every page is named in the tab bar", () => {
    const html = render();
    for (const label of ["Members", "Invitations", "Roles", "Permission matrix", "Teams and departments", "Access scope"]) {
      expect(html).toContain(label);
    }
  });

  test("roles page says the base roles are not editable here", () => {
    const html = render("/settings/team/roles");
    expect(html).toContain("decided by the platform");
  });

  test("matrix page explains that read, write and approve differ", () => {
    const html = render("/settings/team/matrix");
    expect(html).toContain("Reading, writing and approving are three different things");
  });

  test("teams page states that a team grants nothing", () => {
    const html = render("/settings/team/groups");
    expect(html).toContain("A team groups and never grants");
  });

  test("access page keeps branches apart from warehouses and tills", () => {
    const html = render("/settings/team/access");
    expect(html).toContain("a warehouse another and a register a third");
  });

  test("the roster page is the same implementation as /settings/members", () => {
    const html = render("/settings/team/members");
    // the roster table comes from MembersSettings, not a second copy
    expect(html).toContain('data-testid="members-table"');
  });
});
