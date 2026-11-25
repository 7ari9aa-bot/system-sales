import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import definitions from "./receiptDefinitions.fixture.json";
import { Field } from "./ShopPolicySettings";
import { SHOP_PROFILE_KEYS } from "./ShopProfileForm";
import { PRINT_KEYS } from "./PrintAndBarcodeSettings";
import { policyDefinitions } from "@/cashier/api/shopPolicy";

// The definitions are the server's own reply for the business and print domains (taken from the
// settings registry), so these tests draw exactly what an owner would be offered.
const shown = (domain, keys) => policyDefinitions(definitions, { domain, keys });
const draw = (def, value) => renderToStaticMarkup(<Field def={def} value={value} text={value ?? ""} error={null} onChange={() => {}} />);

describe("the shop profile screen", () => {
  const defs = shown("business", SHOP_PROFILE_KEYS);
  it("offers every detail the receipt prints, in order, and nothing else", () => {
    expect(defs.map((d) => d.key)).toEqual(SHOP_PROFILE_KEYS);
    expect(defs).toHaveLength(10);
  });
  it("does not offer the industry choice", () => {
    expect(defs.map((d) => d.key)).not.toContain("business.vertical");
  });
  it("each detail is a text box that keeps what was typed", () => {
    for (const d of defs) {
      const html = draw(d, "007");
      expect(html).toContain('type="text"');
      expect(html).toContain('value="007"');
    }
  });
});

describe("the printed invoice screen", () => {
  const defs = shown("print", PRINT_KEYS);
  const by = Object.fromEntries(defs.map((d) => [d.key, d]));
  it("offers all six receipt settings", () => {
    expect(defs.map((d) => d.key)).toEqual(PRINT_KEYS);
  });
  it("lists paper first, then copies, so the owner meets the roll before the extras", () => {
    expect(defs.slice(0, 2).map((d) => d.key)).toEqual(["print.paper_width", "print.copies"]);
  });
  it("paper width is a dropdown with the server's own choices", () => {
    const html = draw(by["print.paper_width"], "58mm");
    expect(html).toContain("<select");
    expect(html).toMatch(/<option value="58mm" selected/);
    expect(html).toContain('value="80mm"');
  });
  it("copies is a number box", () => {
    expect(draw(by["print.copies"], 2)).toContain('inputMode="decimal"');
  });
  it("logo and tax detail are switches", () => {
    expect(draw(by["print.show_logo"], true)).toContain('role="switch"');
    expect(draw(by["print.show_tax_detail"], false)).toContain('role="switch"');
  });
  it("header and footer are text boxes", () => {
    expect(draw(by["print.header_text"], "أهلاً")).toContain('value="أهلاً"');
    expect(draw(by["print.footer_text"], "شكراً")).toContain('value="شكراً"');
  });
  it("does not offer settings nothing reads yet", () => {
    const all = policyDefinitions(definitions, { domain: "print" }).map((d) => d.key);
    expect(all).not.toContain("print.invoice_prefix");
    expect(all).not.toContain("print.barcode_format");
  });
});
