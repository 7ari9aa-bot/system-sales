import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ReturnReasonSelect, { reasonLabel } from "./ReturnReasonSelect";

describe("ReturnReasonSelect", () => {
  it("shows nothing when the shop set no reasons", () => {
    expect(renderToStaticMarkup(<ReturnReasonSelect reasons={[]} value={null} onChange={() => {}} />)).toBe("");
    expect(renderToStaticMarkup(<ReturnReasonSelect reasons={undefined} value={null} onChange={() => {}} />)).toBe("");
  });
  it("offers 'no reason' plus each of the shop's reasons", () => {
    const html = renderToStaticMarkup(<ReturnReasonSelect reasons={["size", "too_small"]} value={null} onChange={() => {}} />);
    expect(html).toContain("بدون سبب");
    expect(html).toContain("المقاس");
    expect(html).toContain("too_small"); // a reason the owner added shows as written
  });
  it("names the built-in reasons in Arabic and passes custom ones through", () => {
    expect(reasonLabel("defect")).toBe("عيب في القطعة");
    expect(reasonLabel("anything_else")).toBe("anything_else");
  });
});
