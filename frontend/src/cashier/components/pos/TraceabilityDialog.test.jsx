import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TraceabilityDialogBody } from "./TraceabilityDialog";

const renderBody = (props) =>
  renderToStaticMarkup(
    createElement(TraceabilityDialogBody, {
      variant: { id: "v1", productName: "Item Tracked", sku: "SKU-1" },
      quantity: 1,
      traceInfo: { mode: "serial", serials: [{ id: "s1", serial_code: "SN100" }] },
      onConfirm: () => {},
      onBack: () => {},
      ...props,
    })
  );

describe("TraceabilityDialog: serial and batch selection", () => {
  it("renders serial number prompt in serial mode", () => {
    const html = renderBody({
      traceInfo: { mode: "serial", serials: [{ id: "s1", serial_code: "SN100" }] },
    });
    expect(html).toContain("Item Tracked");
    expect(html).toContain("مسح أو إدخال الرقم التسلسلي");
    expect(html).toContain("SN100");
  });

  it("renders lot choices in batch mode with FEFO recommended", () => {
    const html = renderBody({
      traceInfo: {
        mode: "batch",
        lots: [
          { id: "l1", lot_code: "LOT-EARLY", expires_at: "2026-12-01T00:00:00Z" },
          { id: "l2", lot_code: "LOT-LATER", expires_at: "2027-06-01T00:00:00Z" },
        ],
      },
    });
    expect(html).toContain("اختر الدفعة / التشغيلة");
    expect(html).toContain("LOT-EARLY");
    expect(html).toContain("الأقرب انتهاءً (موصى به)");
    expect(html).toContain("LOT-LATER");
  });
});
