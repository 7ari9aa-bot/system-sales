import { describe, expect, it } from "vitest";
import { shopFromUser } from "./shopIdentity";

describe("shopFromUser", () => {
  it("takes the real tenant name", () => expect(shopFromUser({ tenants: [{ name: "  متجر النور " }] })).toEqual({ name: "متجر النور" }));
  it("no tenant / no user -> empty name, never a made-up one", () => {
    expect(shopFromUser(null)).toEqual({ name: "" });
    expect(shopFromUser({ tenants: [] })).toEqual({ name: "" });
    expect(shopFromUser({})).toEqual({ name: "" });
  });
  it("a tenant without a name is empty, not 'undefined'", () => expect(shopFromUser({ tenants: [{}] }).name).toBe(""));
});
