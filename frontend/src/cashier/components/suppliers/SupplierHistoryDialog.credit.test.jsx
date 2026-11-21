import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

// The dialog is a Radix portal; render its content directly so the markup can be inspected.
vi.mock("@/cashier/components/ui/dialog", () => ({
  Dialog: ({ children }) => <div>{children}</div>,
  DialogContent: ({ children }) => <div>{children}</div>,
  DialogHeader: ({ children }) => <div>{children}</div>,
  DialogTitle: ({ children }) => <h2>{children}</h2>,
  DialogDescription: ({ children }) => <div>{children}</div>,
}));

import SupplierHistoryDialog from "./SupplierHistoryDialog";

const supplier = (credit) => ({ id: "sup-1", name: "نيل تكستايل", company: "نيل", phone: "0100", agent: "أحمد", total: 5000, paid: 3000, credit, balance: 2000 });
const draw = (credit) => renderToStaticMarkup(<SupplierHistoryDialog open onOpenChange={() => {}} supplier={supplier(credit)} orders={[]} returns={[]} />);

describe("the supplier history credit figure", () => {
  // A supplier whose returns net to nothing must not read "- 0.00" beside "مرتجعات مخصومة".
  it("writes a plain zero when the deducted returns round to nothing", () => {
    const html = draw(0);
    expect(html).not.toContain("− 0.00");
    expect(html).not.toContain("- 0.00");
    expect(html).toContain("مرتجعات مخصومة");
  });

  it("keeps the minus sign on a real deduction", () => {
    expect(draw(450)).toContain("−450.00");
  });
});
