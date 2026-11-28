import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import PosHeaderBar from "./PosHeaderBar";

const html = (props) => renderToStaticMarkup(<PosHeaderBar invoiceNo="POS-1" cashier="سارة" {...props} />);

// The button hands the open drawer to another cashier. Called "shift handover" it read like closing the day,
// so it names who receives it, and its hint says it does not close the day.
describe("PosHeaderBar handover button", () => {
  it("names the receiver instead of sounding like a day close", () => {
    const h = html({ onHandover: () => {} });
    expect(h).toContain("تسليم لكاشير آخر");
    expect(h).not.toContain(">تسليم وردية<");
    expect(h).toContain("من غير إغلاق اليوم");
  });
  it("is absent when handover is not offered", () => {
    expect(html({})).not.toContain("تسليم لكاشير آخر");
  });
});
