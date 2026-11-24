import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import PendingRefundsPanel from "./PendingRefundsPanel";

const row = { refund_id: "r1", method: "card", amount: "100.00" };

describe("the pending refunds panel", () => {
  it("shows the card amount that still has to be reversed on the terminal", () => {
    const html = renderToStaticMarkup(<PendingRefundsPanel pending={[row]} />);
    expect(html).toContain("بطاقة");
    expect(html).toContain("100.00");
    expect(html).toContain("رقم المرجع");
  });

  it("will not confirm without the terminal reference", () => {
    // Confirming an empty reference is what would let the till claim a reversal nobody made.
    const html = renderToStaticMarkup(<PendingRefundsPanel pending={[row]} />);
    expect(html).toMatch(/disabled[^>]*>تأكيد الرد/);
  });

  it("renders nothing when the refund settled on the spot", () => {
    expect(renderToStaticMarkup(<PendingRefundsPanel pending={[]} />)).toBe("");
  });
});
