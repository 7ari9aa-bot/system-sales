import { describe, expect, it } from "vitest";
import { deadStockErrorNotice } from "@/cashier/components/reports/deadStockView";
import { profitErrorNotice } from "@/cashier/components/reports/profitView";
import { sellThroughErrorNotice } from "@/cashier/components/reports/sellThroughView";
import { markdownErrorMessage } from "@/cashier/components/inventory/seasonMarkdownView";

// A refusal can now come from the shop owner's own setting (managers may be kept out of cost and
// profit), so no message may promise a manager the screen. Each must say the owner decides, and
// none may send the reader to "the manager" or offer a retry that cannot work.
const refusals = {
  profit: profitErrorNotice({ status: 403 }).message,
  sellThrough: sellThroughErrorNotice({ status: 403 }, "forbidden").message,
  deadStock: deadStockErrorNotice({ status: 403 }, "forbidden").message,
  markdown: markdownErrorMessage("forbidden"),
};

describe.each(Object.entries(refusals))("the refusal for %s", (_name, message) => {
  it("names the shop owner as the one who decides", () => {
    expect(message).toMatch(/صاحب المحل/);
    expect(message).toMatch(/سمح/);
  });
  it("never says the manager can always open it", () => {
    expect(message).not.toMatch(/أو المدير بس/);
    expect(message).not.toMatch(/اطلب من المدير/);
  });
  it("is not a retry prompt", () => {
    expect(message).not.toMatch(/حاول مرة|جرّب تاني|أعد المحاولة/);
  });
  it("points to the owner, who is the one who can fix it", () => {
    expect(message).toMatch(/اطلب من صاحب المحل/);
  });
});

it("the four refusals are all different messages", () => {
  expect(new Set(Object.values(refusals)).size).toBe(4);
});
