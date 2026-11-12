import { describe, expect, it } from "vitest";
import { createProfileBody, updateProfileBody } from "./posProfileBody";

const base = { name: "كاشير", code: "P1", warehouse_id: "w1", default_payment_method: "cash", allowed_payment_methods: ["cash"] };

describe("require_customer reaches the server as the checkbox says", () => {
  it("is true when ticked, on create and on edit", () => {
    expect(createProfileBody({ ...base, require_customer: true, max_discount_pct: "" }).require_customer).toBe(true);
    expect(updateProfileBody({ ...base, require_customer: true }).require_customer).toBe(true);
  });
  it("is an explicit false when unticked, so an edit can switch it OFF", () => {
    expect(updateProfileBody({ ...base, require_customer: false }).require_customer).toBe(false);
    expect(updateProfileBody({ ...base, require_customer: undefined }).require_customer).toBe(false);
  });
});

describe("the discount ceiling: blank means 'none' but says it differently on create and edit", () => {
  it("is left out on create when blank", () => {
    expect("max_discount_pct" in JSON.parse(JSON.stringify(createProfileBody({ ...base, max_discount_pct: "  " })))).toBe(false);
  });
  it("is null on edit when the owner emptied it, which removes the ceiling", () => {
    for (const blankValue of ["", "  ", null, undefined]) {
      expect(updateProfileBody({ ...base, max_discount_pct: blankValue }).max_discount_pct).toBeNull();
    }
  });
  it("is the trimmed text when set, never a number that could round", () => {
    expect(updateProfileBody({ ...base, max_discount_pct: " 12.50 " }).max_discount_pct).toBe("12.50");
    expect(createProfileBody({ ...base, max_discount_pct: "20" }).max_discount_pct).toBe("20");
  });
  it("keeps 0 as a real ceiling (no discount at all), not as blank", () => {
    expect(updateProfileBody({ ...base, max_discount_pct: 0 }).max_discount_pct).toBe("0");
    expect(updateProfileBody({ ...base, max_discount_pct: "0" }).max_discount_pct).toBe("0");
  });
});
