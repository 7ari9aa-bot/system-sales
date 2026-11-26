/**
 * A masked setting must never be drawn as a normal control.
 *
 * The server redacts a SENSITIVE value the caller may not read as the string "******".
 * Rendered into a switch, that string is truthy — so a setting whose real value was false
 * showed as ON, and a number box got an invalid number the user could type over. These
 * tests pin the redacted field and the save guard that keeps the mask out of the payload.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MASKED_VALUE, SettingField, isProtectedValue } from "./UnifiedSettings";
import { isMaskedValue } from "@/components/settings/useSettings";

const base = { label_ar: "حقل", label_en: "Field", description_ar: "وصف", description_en: "Desc" };
const draw = (def, value) =>
  renderToStaticMarkup(<SettingField defn={{ ...base, ...def }} value={value} onChange={() => {}} isAr />);

describe("redacted sensitive settings", () => {
  it("a masked value is recognised as a redaction, not a value", () => {
    expect(isProtectedValue(MASKED_VALUE)).toBe(true);
    expect(isProtectedValue("false")).toBe(false);
    expect(isMaskedValue(MASKED_VALUE)).toBe(true);
    expect(isMaskedValue(false)).toBe(false);
  });

  it("a masked bool is a protected field, never a switch that reads as ON", () => {
    const html = draw({ key: "team.require_2fa", type: "bool" }, MASKED_VALUE);

    expect(html).toContain('data-testid="setting-protected"');
    expect(html).toContain("محمي");
    expect(html).toContain("disabled");
    expect(html).not.toContain('role="switch"');
    expect(html).not.toContain("aria-checked");
    expect(html).not.toContain("******");
  });

  it("a masked number is not a number box and a masked enum is not a select", () => {
    const number = draw({ key: "pos.cash_movement_limit", type: "number" }, MASKED_VALUE);
    const enumField = draw(
      { key: "pos.deduct_stock_on", type: "enum", allowed_values: ["sale", "payment"] },
      MASKED_VALUE,
    );

    expect(number).not.toContain('type="number"');
    expect(enumField).not.toContain("<select");
    expect(enumField).toContain('data-testid="setting-protected"');
  });

  it("an unmasked bool still renders its real state", () => {
    const html = draw({ key: "team.require_2fa", type: "bool" }, false);
    expect(html).toContain('aria-checked="false"');
    expect(html).not.toContain('data-testid="setting-protected"');
  });
});
