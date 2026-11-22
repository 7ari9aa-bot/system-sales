import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import PosInvoiceTable from "./PosInvoiceTable";

// The add button's own opening tag, so the test never reads another button's attributes.
const addTag = (markup) => (markup.match(/<button[^>]*>(?=إضافة<\/button>)/) || [""])[0];

const html = (barcode) =>
  renderToStaticMarkup(
    <PosInvoiceTable lines={[]} totals={{}} barcode={barcode} onBarcodeChange={() => {}} onBarcodeSubmit={() => {}} />,
  );

// The barcode box answers only to Enter. A touch till has no Enter key, so a visible add button must sit beside it.
describe("PosInvoiceTable add button", () => {
  it("shows an add button in the entry row", () => {
    expect(addTag(html(""))).toContain("<button");
    expect(html("")).toContain(">إضافة</button>");
  });
  it("is disabled while the box is empty or only spaces", () => {
    expect(addTag(html(""))).toContain('disabled=""');
    expect(addTag(html("   "))).toContain('disabled=""');
  });
  it("is enabled once there is something typed", () => {
    const tag = addTag(html("2991000102947"));
    expect(tag).toContain("<button");
    expect(tag).not.toContain('disabled=""');
  });
});
