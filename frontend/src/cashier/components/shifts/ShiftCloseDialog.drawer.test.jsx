import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

// The dialog is a Radix portal; render its content directly so the markup can be inspected.
vi.mock("@/cashier/components/ui/dialog", () => ({
  Dialog: ({ children }) => <div>{children}</div>,
  DialogContent: ({ children }) => <div>{children}</div>,
  DialogHeader: ({ children }) => <div>{children}</div>,
  DialogFooter: ({ children }) => <div>{children}</div>,
  DialogTitle: ({ children }) => <h2>{children}</h2>,
  DialogDescription: ({ children }) => <p>{children}</p>,
}));
vi.mock("react-router-dom", () => ({ Link: ({ children }) => <a>{children}</a> }));

import ShiftCloseDialog from "./ShiftCloseDialog";

const shift = { id: "s1", number: "7", employee: "منى", openingCash: 200 };
const preview = (take) => ({ take_payments: take, closing_balance: "500.00", opening_balance: "200.00", sales_total: "300.00", invoice_count: 3, return_count: 0, returns_total: "0.00" });
// The confirm button's real `disabled` attribute (the Tailwind class "disabled:..." is on every button and means nothing).
const confirmDisabled = (html) => {
  const btn = html.match(/<button[^>]*>(?:(?!<\/button>).)*تأكيد إغلاق اليوم(?:(?!<\/button>).)*<\/button>/s)?.[0] ?? "";
  if (!btn) throw new Error("confirm button not found");
  return /\sdisabled(=""|\s|>)/.test(btn.split(">")[0]);
};
const render = (props) => renderToStaticMarkup(<ShiftCloseDialog open onOpenChange={() => {}} shift={shift} onSubmit={() => {}} {...props} />);

describe("a till with a drawer", () => {
  const html = render({ preview: preview(true), drawer: { expected_cash: "500.00" }, rules: { reasonRequired: true, threshold: 0 } });
  it("asks for the counted cash and shows what the drawer should hold", () => {
    expect(html).toContain('data-testid="drawer-count"');
    expect(html).toContain("النقدية الفعلية");
    expect(html).toContain("المتوقع في الدرج");
  });
  it("does not say the close counts nothing", () => {
    expect(html).not.toContain("لا يُطلب عدّ الدرج");
  });
  it("keeps the confirm button off until a count is entered", () => {
    expect(confirmDisabled(html)).toBe(true);
  });
  it("waits for the expected figure rather than closing blind", () => {
    const blind = render({ preview: preview(true), drawer: null });
    expect(confirmDisabled(blind)).toBe(true);
  });
});

describe("a till with no drawer", () => {
  const html = render({ preview: preview(false), drawer: null });
  it("closes exactly as before: no count, the old note, button ready", () => {
    expect(html).not.toContain('data-testid="drawer-count"');
    expect(html).toContain("لا يُطلب عدّ الدرج");
    expect(confirmDisabled(html)).toBe(false);
  });
});

describe("before the preview has loaded", () => {
  it("shows no count form and keeps the button off", () => {
    const html = render({ preview: undefined, previewLoading: true });
    expect(html).not.toContain('data-testid="drawer-count"');
    expect(confirmDisabled(html)).toBe(true);
  });
});

describe("the returns row", () => {
  // A day whose returns net to a few piastres must not read "-0.00" on the screen the cashier confirms.
  const withReturns = (returns_total) => render({ preview: { ...preview(false), returns_total }, drawer: null });

  it("writes a plain zero when the returns round to nothing", () => {
    const html = withReturns("0.00");
    expect(html).not.toContain("−0.00");
    expect(html).not.toContain("-0.00");
    expect(html).toContain("0.00");
  });

  it("keeps the minus sign on a real return", () => {
    const html = withReturns("120.50");
    expect(html).toContain("−120.50");
  });

  it("never writes a double minus when the server already sent one", () => {
    const html = withReturns("-120.50");
    expect(html).toContain("−120.50");
    expect(html).not.toContain("−−");
  });
});
