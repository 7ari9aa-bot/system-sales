import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Field } from "./ShopPolicySettings";

const base = { domain: "einvoice", enforced: true, scopes: ["tenant"], label_ar: "الحقل", description_ar: "وصف" };
const draw = (def, value, error) => renderToStaticMarkup(<Field def={def} value={value} text={value ?? ""} error={error} onChange={() => {}} />);

describe("Field draws the right control for each kind of setting", () => {
  it("a text setting is a text box that keeps what was typed, never a number box", () => {
    const html = draw({ ...base, key: "einvoice.branch_code", type: "string", default: "", max_length: 120 }, "007");
    expect(html).toContain('type="text"');
    expect(html).toContain('value="007"');
    expect(html).not.toContain('inputMode="decimal"');
    expect(html).toContain('maxLength="120"');
  });

  it("a choice is a dropdown listing every allowed value by its Arabic name, with the saved one selected", () => {
    const html = draw(
      { ...base, key: "einvoice.default_payment_method", type: "enum", default: "C", allowed_values: ["C", "V", "O"] },
      "V",
    );
    expect(html).toContain("<select");
    expect(html).toContain("نقدي");
    expect(html).toContain("فيزا");
    expect(html).toContain("أخرى (محفظة، إنستاباي، تحويل)");
    expect(html).toMatch(/<option value="V" selected/);
  });

  it("a number is still a number box", () => {
    const html = draw({ ...base, key: "einvoice.warn_hours_before_deadline", type: "number", default: 24, min_value: 1, max_value: 96 }, "24");
    expect(html).toContain('inputMode="decimal"');
  });

  it("an on/off setting is a switch", () => {
    const html = draw({ ...base, key: "einvoice.eta_enabled", type: "bool", default: false }, false);
    expect(html).toContain('role="switch"');
  });

  it("a kind it cannot edit says so instead of drawing a wrong control", () => {
    const html = draw({ ...base, key: "x.y", type: "mystery", default: null }, null);
    expect(html).toContain("لا يمكن تعديله من هنا");
    expect(html).not.toContain("<input");
  });

  it("shows the server's problem with a field", () => {
    expect(draw({ ...base, key: "a", type: "string", default: "" }, "x", "الحد الأقصى 5 حرفًا")).toContain("الحد الأقصى 5 حرفًا");
  });
});
