/**
 * The workspace section: five real pages, and the boundaries the map draws.
 *
 * What matters here is not the markup but the promises: the tab bar reaches every
 * page the map lists, the identifier is shown and NOT offered as an editable field
 * (other systems already hold it as an address), ownership transfer is described
 * instead of drawn as a button that cannot work, and the shared-defaults page is
 * read-only so no setting is editable in two places.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import WorkspaceSettings, { WORKSPACE_SECTION_SLUGS, resolveWorkspaceSection } from "./WorkspaceSettings";

vi.mock("@/lib/api", () => ({
  api: vi.fn(() => Promise.resolve(null)),
}));

// The data page reads the signed-in workspace from the auth context; the rest of the
// section does not, so the stub is only what those pages need to render.
vi.mock("@/lib/regional", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useRegional: () => ({
      countryCode: "EG",
      setCountryCode: vi.fn(),
      country: {
        code: "EG",
        currency: "EGP",
        currencyName: "Egyptian Pound",
        currencyNameAr: "جنيه مصري",
        timezone: "Africa/Cairo",
        dateLocale: "ar-EG",
        name: "Egypt",
        nameAr: "مصر",
      },
      countries: {
        EG: {
          code: "EG",
          currency: "EGP",
          currencyName: "Egyptian Pound",
          currencyNameAr: "جنيه مصري",
          timezone: "Africa/Cairo",
          dateLocale: "ar-EG",
          name: "Egypt",
          nameAr: "مصر",
        },
      },
    }),
  };
});

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

const render = (path = "/settings/workspace") =>
  renderToStaticMarkup(
    <I18nProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/settings/workspace" element={<WorkspaceSettings />} />
          <Route path="/settings/workspace/:section" element={<WorkspaceSettings />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>
  );

describe("WorkspaceSettings", () => {
  test("the five pages of the map each have a route", () => {
    expect(WORKSPACE_SECTION_SLUGS).toEqual(["overview", "data", "ownership", "switch", "defaults"]);
  });

  test("an unknown or missing section falls back to the overview", () => {
    expect(resolveWorkspaceSection(undefined).value).toBe("overview");
    expect(resolveWorkspaceSection("nonsense").value).toBe("overview");
    expect(resolveWorkspaceSection("ownership").value).toBe("ownership");
  });

  test("every page is reachable from the tab bar", () => {
    const html = render();
    // One tab per section, and no more: the loop is over the slugs so a section
    // added to the list without a tab (or a stray tab without a section) fails here.
    expect(html.match(/role="tab"/g)).toHaveLength(WORKSPACE_SECTION_SLUGS.length);
    // the bar names all five (the test provider defaults to English)
    expect(html).toContain("Overview");
    expect(html).toContain("Workspace data");
    expect(html).toContain("Ownership");
    expect(html).toContain("Manage workspaces");
    expect(html).toContain("Shared defaults");
  });

  test("the overview says a workspace is not the store", () => {
    const html = render("/settings/workspace/overview");
    expect(html).toContain("A workspace is not the store");
  });

  test("ownership transfer is explained, never offered as a dead button", () => {
    const html = render("/settings/workspace/ownership");
    expect(html).toContain("Ownership transfer");
    expect(html).toContain("not available from this screen yet");
  });

  test("the shared defaults are read-only with a link to the owning page", () => {
    const html = render("/settings/workspace/defaults");
    expect(html).toContain("This page is read-only");
    expect(html).toContain("/settings/workspace/data");
    expect(html).toContain("/settings/ai");
    // no form control on a page that must not write
    expect(html).not.toContain("<input");
    expect(html).not.toContain("<select");
  });

  test("the data page keeps the identifier out of the editable fields", () => {
    const html = render("/settings/workspace/data");
    // the name is editable; the slug is displayed as text only
    expect(html).toContain('data-testid="workspace-name"');
    expect(html).not.toContain('data-testid="workspace-slug"');
  });
});
