import { describe, expect, it } from "vitest";
import { SECTIONS, TAX_DOMAINS, readiness, sectionDefs, FRIENDLY } from "./taxSettings";

const def = (key, extra = {}) => ({ key, domain: key.split(".")[0], type: "string", enforced: true, scopes: ["tenant"], ...extra });
const ALL_KEYS = [
  "business.legal_name", "business.trade_name", "business.tax_id",
  "business.address.line1", "business.address.city", "business.address.postal_code", "business.phone", "business.email", "business.website",
  "einvoice.eta_enabled", "einvoice.settings_confirmed", "einvoice.prices_include_vat", "einvoice.vat_category",
  "einvoice.default_payment_method", "einvoice.split_payment_rule", "einvoice.unit_code", "einvoice.delivery_mode",
  "einvoice.warn_hours_before_deadline", "einvoice.branch_code", "einvoice.activity_code", "einvoice.branch_governate",
  "einvoice.branch_region_city", "einvoice.branch_street", "einvoice.branch_building_number",
];
const defs = ALL_KEYS.map((k) => def(k));
const vals = (o = {}) => ({
  "business.legal_name": "شركة س", "business.tax_id": "123456789", "einvoice.eta_enabled": true, "einvoice.settings_confirmed": true,
  "einvoice.branch_code": "0", "einvoice.activity_code": "4771", "einvoice.branch_governate": "القاهرة",
  "einvoice.branch_region_city": "مدينة نصر", "einvoice.branch_street": "شارع التسعين", "einvoice.branch_building_number": "5", ...o,
});

describe("the sections", () => {
  it("run in the order a merchant fills them: who you are, how you price, how you are paid, where you are, then the rest", () => {
    expect(SECTIONS.map((s) => s.id)).toEqual(["identity", "pricing", "payment", "branch", "advanced"]);
  });

  it("every setting is in exactly one section, so nothing is lost and nothing shows twice", () => {
    const seen = SECTIONS.flatMap((s) => sectionDefs(s, defs).map((d) => d.key));
    // The panel owns the switch and the confirmation; the shop-details tab owns the address, phone,
    // email and website. Everything else is here, once.
    const elsewhere = /^(business\.(address\.|phone|email|website)|einvoice\.(eta_enabled|settings_confirmed))/;
    expect(seen.sort()).toEqual(ALL_KEYS.filter((k) => !elsewhere.test(k)).sort());
    expect(new Set(seen).size).toBe(seen.length);
  });

  it("a setting the server adds later still shows (in the last section), never silently hidden", () => {
    const extra = [...defs, def("einvoice.something_new")];
    expect(SECTIONS.flatMap((s) => sectionDefs(s, extra)).map((d) => d.key)).toContain("einvoice.something_new");
  });

  it("business settings that are not tax never appear: business type, size/colour matrix, batches, weighing", () => {
    const noise = ["business.vertical", "business.type", "business.feature.size_color", "business.feature.batches", "business.feature.weighing"];
    const keys = SECTIONS.flatMap((s) => sectionDefs(s, [...defs, ...noise.map((k) => def(k))])).map((d) => d.key);
    for (const k of noise) expect(keys).not.toContain(k);
  });

  it("the on/off switch and the confirmation are not in a section: they are the status panel's", () => {
    const keys = SECTIONS.flatMap((s) => sectionDefs(s, defs)).map((d) => d.key);
    expect(keys).not.toContain("einvoice.eta_enabled");
    expect(keys).not.toContain("einvoice.settings_confirmed");
  });

  it("the tab reads both domains", () => {
    expect(TAX_DOMAINS).toEqual(["business", "einvoice"]);
  });
});

describe("is the e-receipt really going out?", () => {
  it("yes when it is on, confirmed, and the shop's tax data is complete", () => {
    expect(readiness(vals())).toMatchObject({ state: "running", missing: [] });
  });

  it("off says it is off, plainly, and nothing is wrong", () => {
    const r = readiness(vals({ "einvoice.eta_enabled": false }));
    expect(r.state).toBe("off");
  });

  it("on but not confirmed is STOPPED, and says why: this is the silent stop", () => {
    const r = readiness(vals({ "einvoice.settings_confirmed": false }));
    expect(r.state).toBe("blocked");
    expect(r.reasons.join(" ")).toMatch(/أكّد/);
  });

  it.each([
    ["business.tax_id", "الرقم الضريبي"],
    ["einvoice.branch_code", "كود الفرع"],
    ["einvoice.activity_code", "كود النشاط"],
    ["einvoice.branch_governate", "المحافظة"],
    ["einvoice.branch_region_city", "المدينة"],
    ["einvoice.branch_street", "الشارع"],
    ["einvoice.branch_building_number", "رقم المبنى"],
  ])("an empty %s is named, so the merchant knows what to fill", (key, word) => {
    const r = readiness(vals({ [key]: "" }));
    expect(r.state).toBe("blocked");
    expect(r.missing.join(" ")).toContain(word);
  });

  it("the shop's name may be the legal name OR the trade name, as the server accepts either", () => {
    expect(readiness(vals({ "business.legal_name": "", "business.trade_name": "ماركة س" })).missing).toEqual([]);
    const none = readiness(vals({ "business.legal_name": "", "business.trade_name": "" }));
    expect(none.state).toBe("blocked");
    expect(none.missing.join(" ")).toContain("اسم المحل");
  });

  it("the tax number must be exactly 9 digits, the authority refuses anything else", () => {
    for (const bad of ["12345678", "1234567890", "12345678a", "١٢٣٤٥٦٧٨٩"]) {
      const r = readiness(vals({ "business.tax_id": bad }));
      expect(r.state, bad).toBe("blocked");
      expect(r.missing.join(" ")).toContain("الرقم الضريبي");
    }
    expect(readiness(vals({ "business.tax_id": " 123456789 " })).state).toBe("running");
  });

  it("Arabic-Indic digits are refused AND the merchant is told to type English digits, not just 'wrong'", () => {
    const r = readiness(vals({ "business.tax_id": "١٢٣٤٥٦٧٨٩", "einvoice.activity_code": "٤٧٧١" }));
    expect(r.state).toBe("blocked");
    expect(r.missing.join(" ")).toContain("أرقام إنجليزية");
    expect(r.missing).toHaveLength(2);
  });

  it("the activity code must be exactly 4 digits", () => {
    for (const bad of ["477", "47711", "47a1"]) {
      expect(readiness(vals({ "einvoice.activity_code": bad })).state, bad).toBe("blocked");
    }
  });

  it("a branch code of 0 is a real code (the first branch), not an empty one", () => {
    expect(readiness(vals({ "einvoice.branch_code": "0" })).missing).toEqual([]);
  });

  it("spaces only count as empty", () => {
    expect(readiness(vals({ "business.tax_id": "   " })).missing.join(" ")).toContain("الرقم الضريبي");
  });

  it("everything missing is listed at once, not one at a time", () => {
    const r = readiness(vals({ "business.tax_id": "", "einvoice.activity_code": "", "einvoice.branch_street": "" }));
    expect(r.missing).toHaveLength(3);
  });
});

describe("plain words instead of codes", () => {
  it("the technical delivery mode and unit code get a human name", () => {
    expect(FRIENDLY["einvoice.delivery_mode"].label).not.toMatch(/FC|TO|TC/);
    expect(FRIENDLY["einvoice.unit_code"].label).not.toMatch(/\bEA\b/);
  });
  it("the deadline warning says what it warns about", () => {
    expect(FRIENDLY["einvoice.warn_hours_before_deadline"].label).toMatch(/رفض|مهلة/);
  });
});
