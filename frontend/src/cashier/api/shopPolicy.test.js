import { describe, expect, it } from "vitest";
import { CHOICE_LABELS_AR, changedValues, choiceLabel, parseChoice, parseNumber, parseReasons, parseText, policyDefinitions, policyErrorMessage, reasonsToText, startingValues } from "./shopPolicy";

const def = (o) => ({ domain: "pos", enforced: true, scopes: ["tenant", "branch"], default: 30, min_value: 0, max_value: 365, ...o });

describe("policyDefinitions", () => {
  it("keeps only enforced, tenant-wide settings of the domain", () => {
    const defs = [
      def({ key: "a" }),
      def({ key: "not-wired", enforced: false }),
      def({ key: "other-domain", domain: "print" }),
      def({ key: "branch-only", scopes: ["branch"] }),
    ];
    expect(policyDefinitions(defs).map((d) => d.key)).toEqual(["a"]);
  });
  it("copes with nothing loaded yet", () => {
    expect(policyDefinitions(undefined)).toEqual([]);
  });
});

describe("startingValues and changedValues", () => {
  const defs = [def({ key: "a", default: 30 }), def({ key: "b", default: true })];
  it("starts from the server's effective value, else the default", () => {
    expect(startingValues(defs, { a: { value: 14 } })).toEqual({ a: 14, b: true });
  });
  it("lists only what changed", () => {
    const o = { a: 14, b: true };
    expect(changedValues(defs, o, { a: 14, b: true })).toEqual([]);
    expect(changedValues(defs, o, { a: 21, b: true })).toEqual([{ key: "a", value: 21 }]);
  });
  it("compares lists by content", () => {
    const d = [def({ key: "r", default: [] })];
    expect(changedValues(d, { r: ["x"] }, { r: ["x"] })).toEqual([]);
    expect(changedValues(d, { r: ["x"] }, { r: ["x", "y"] })).toHaveLength(1);
  });
});

describe("parseNumber", () => {
  const d = def({ key: "a" });
  it("accepts a number inside the bounds, including 0", () => {
    expect(parseNumber(d, "14")).toEqual({ value: 14 });
    expect(parseNumber(d, "0")).toEqual({ value: 0 });
  });
  it("refuses out-of-range and non-numbers", () => {
    expect(parseNumber(d, "400").error).toMatch(/365/);
    expect(parseNumber(d, "-1").error).toMatch(/0/);
    expect(parseNumber(d, "abc").error).toBeTruthy();
  });
  it("treats an empty box as 'no limit' only when the setting has no default", () => {
    expect(parseNumber(def({ key: "x", default: null }), "")).toEqual({ value: null });
    expect(parseNumber(d, "").error).toBeTruthy();
  });
});

describe("reasons text", () => {
  it("one per line, trimmed, no blanks or repeats", () => {
    expect(parseReasons(" size \n\ndefect\nsize\n  \nwrong_item")).toEqual(["size", "defect", "wrong_item"]);
  });
  it("round-trips", () => {
    expect(parseReasons(reasonsToText(["a", "b"]))).toEqual(["a", "b"]);
    expect(parseReasons(undefined)).toEqual([]);
  });
});

describe("policyErrorMessage", () => {
  it("explains a permission refusal and passes anything else through", () => {
    expect(policyErrorMessage(new Error("missing permission: settings:write"))).toMatch(/صلاحية/);
    expect(policyErrorMessage(new Error("value out of range"))).toBe("value out of range");
    expect(policyErrorMessage(null)).toBe("تعذّر الحفظ");
  });
});

describe("text and choice settings (the e-receipt screen)", () => {
  const text = def({ key: "einvoice.branch_code", type: "string", default: "", max_length: 120 });
  const choice = def({
    key: "einvoice.vat_category",
    type: "enum",
    default: "taxable",
    allowed_values: ["taxable", "exempt", "non_taxable"],
  });

  it("starts a text box from the saved text, never a number", () => {
    expect(startingValues([text], { "einvoice.branch_code": { value: "007" } })).toEqual({ "einvoice.branch_code": "007" });
  });
  it("keeps a branch code's leading zeros: text is not parsed as a number", () => {
    expect(parseText(text, "007")).toEqual({ value: "007" });
  });
  it("trims text and refuses what is too long", () => {
    expect(parseText(text, "  7  ")).toEqual({ value: "7" });
    expect(parseText(text, "x".repeat(121)).error).toMatch(/120/);
  });
  it("lets a text setting be emptied (the merchant has not filled it in)", () => {
    expect(parseText(text, "")).toEqual({ value: "" });
  });
  it("accepts only one of the allowed choices", () => {
    expect(parseChoice(choice, "exempt")).toEqual({ value: "exempt" });
    expect(parseChoice(choice, "whatever").error).toBeTruthy();
  });
  it("lists a changed choice and leaves an untouched one alone", () => {
    const o = { "einvoice.vat_category": "taxable", "einvoice.branch_code": "7" };
    expect(changedValues([choice, text], o, { ...o, "einvoice.vat_category": "exempt" })).toEqual([
      { key: "einvoice.vat_category", value: "exempt" },
    ]);
  });
});

describe("policyDefinitions for several domains at once", () => {
  it("keeps the settings of every domain asked for, in the order the server sent them", () => {
    const defs = [
      def({ key: "business.tax_id", domain: "business" }),
      def({ key: "einvoice.branch_code", domain: "einvoice" }),
      def({ key: "pos.x", domain: "pos" }),
    ];
    expect(policyDefinitions(defs, { domain: ["business", "einvoice"] }).map((d) => d.key)).toEqual([
      "business.tax_id",
      "einvoice.branch_code",
    ]);
  });
  it("still hides a setting nothing reads, whichever domain it is in", () => {
    const defs = [def({ key: "business.website", domain: "business", enforced: false })];
    expect(policyDefinitions(defs, { domain: ["business"] })).toEqual([]);
  });
});

describe("policyDefinitions for another domain", () => {
  it("takes the domain it is asked for", () => {
    const defs = [def({ key: "a" }), def({ key: "b", domain: "einvoice" })];
    expect(policyDefinitions(defs, { domain: "einvoice" }).map((d) => d.key)).toEqual(["b"]);
  });
});

describe("friendly names for coded choices", () => {
  it("names every payment method the authority defines", () => {
    const d = def({ key: "einvoice.default_payment_method" });
    for (const code of ["C", "V", "CC", "VC", "VO", "PR", "GC", "P", "O"]) {
      expect(choiceLabel(d, code)).not.toBe(code);
    }
  });
  it("names every choice the server allows for the e-receipt settings (none left as a bare code)", () => {
    const allowed = {
      "einvoice.default_payment_method": ["C", "V", "CC", "VC", "VO", "PR", "GC", "P", "O"],
      "einvoice.vat_category": ["taxable", "exempt", "non_taxable"],
      "einvoice.delivery_mode": ["FC", "TO", "TC"],
    };
    for (const [key, values] of Object.entries(allowed)) {
      expect(Object.keys(CHOICE_LABELS_AR[key]).sort()).toEqual([...values].sort());
    }
  });
  it("falls back to the stored value for a choice it has no name for", () => {
    expect(choiceLabel(def({ key: "x.y" }), "zzz")).toBe("zzz");
  });
});
