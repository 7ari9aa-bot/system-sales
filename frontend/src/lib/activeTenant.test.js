import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ getTokens: () => ({ session: true }) }));

const { activeTenant, activeTenantId } = await import("./activeTenant");

const membership = { id: "t1", name: "Shop", slug: "shop", role_code: "owner" };

describe("activeTenantId", () => {
  it("answers with the account's single membership", () => {
    expect(activeTenantId({ tenants: [membership] })).toBe("t1");
  });

  it("refuses to guess when the account belongs to more than one workspace", () => {
    expect(activeTenantId({ tenants: [membership, { ...membership, id: "t2" }] })).toBeNull();
  });

  it("answers null for a signed-in account with no workspace", () => {
    expect(activeTenantId({ tenants: [] })).toBeNull();
    expect(activeTenantId(null)).toBeNull();
  });
});

describe("activeTenant", () => {
  it("returns the membership row, not just its id", () => {
    expect(activeTenant({ tenants: [membership] })).toEqual(membership);
  });

  it("returns null when the workspace cannot be resolved", () => {
    expect(activeTenant({ tenants: [] })).toBeNull();
  });
});
