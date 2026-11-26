/**
 * The scope picker must offer the tenant's own rows by name.
 *
 * It used to be a free-text UUID box, so the only scope anyone could use was the tenant
 * one. These tests pin the loader that turns each scope into labelled options, and the
 * tenant case that must not ask for an id at all.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi, beforeEach } from "vitest";
import ScopeSelector from "@/components/settings/ScopeSelector";
import { loadScopeOptions, SCOPES_WITH_PICKER } from "@/components/settings/scopeOptions";

const apiCached = vi.fn();
vi.mock("@/lib/api", () => ({ apiCached: (...args) => apiCached(...args) }));

describe("ScopeSelector", () => {
  beforeEach(() => apiCached.mockReset());

  it("asks for no id at tenant level", () => {
    const html = renderToStaticMarkup(
      <ScopeSelector scope="tenant" scopeId={null} onScopeChange={() => {}} onScopeIdChange={() => {}} />,
    );
    expect(html).not.toContain("UUID");
    expect(html).not.toContain("Pick by name");
  });

  it("renders a name picker for a real scope instead of a UUID field", () => {
    const html = renderToStaticMarkup(
      <ScopeSelector scope="warehouse" scopeId={null} onScopeChange={() => {}} onScopeIdChange={() => {}} isAr />,
    );
    expect(html).not.toContain("UUID");
    // Two comboboxes: the scope, then the name of the entity in that scope.
    expect(html.match(/role="combobox"/g)).toHaveLength(2);
  });
});

describe("loadScopeOptions", () => {
  beforeEach(() => apiCached.mockReset());

  it("covers every non-tenant scope that has rows", () => {
    expect(SCOPES_WITH_PICKER.sort()).toEqual(
      ["branch", "channel", "pos_profile", "register", "user", "warehouse", "workspace"].sort(),
    );
  });

  it("lists warehouses by name", async () => {
    apiCached.mockResolvedValue([
      { id: "w-1", name: "المخزن الرئيسي" },
      { id: "w-2" },
    ]);
    const options = await loadScopeOptions("warehouse");
    expect(apiCached).toHaveBeenCalledWith("/warehouses", { ttlMs: 0 });
    expect(options[0]).toEqual({ id: "w-1", name: "المخزن الرئيسي" });
    // A row with no name still gets a usable label rather than an empty entry.
    expect(options[1]).toEqual({ id: "w-2", name: "w-2" });
  });

  it("builds the branch list through its workspace", async () => {
    apiCached.mockImplementation((path) => {
      if (path === "/hierarchy/workspaces") {
        return Promise.resolve({ items: [{ id: "ws-1", name: "المحل" }] });
      }
      if (path === "/hierarchy/workspaces/ws-1/locations") {
        return Promise.resolve({ items: [{ id: "loc-1", name: "فرع المعادي" }] });
      }
      return Promise.resolve({ items: [] });
    });
    const options = await loadScopeOptions("branch");
    expect(apiCached).toHaveBeenCalledWith("/hierarchy/workspaces/ws-1/locations", {
      ttlMs: 0,
    });
    expect(options).toEqual([{ id: "loc-1", name: "فرع المعادي", hint: "المحل" }]);
  });

  it("marks a non-channel integration unusable, because the backend refuses it", async () => {
    apiCached.mockResolvedValue([
      { id: "i-1", provider: "whatsapp", kind: "channel", display_name: "واتساب المحل" },
      { id: "i-2", provider: "gmail", kind: "oauth", display_name: "بريد" },
    ]);
    const options = await loadScopeOptions("channel");
    expect(options[0]).toMatchObject({ id: "i-1", name: "واتساب المحل" });
    expect(options[1].disabled).toBe(true);
  });

  it("returns nothing for the tenant scope, which has no rows to pick", async () => {
    expect(await loadScopeOptions("tenant")).toEqual([]);
    expect(apiCached).not.toHaveBeenCalled();
  });
});
