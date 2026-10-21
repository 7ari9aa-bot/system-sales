import { describe, expect, it } from "vitest";
import { heldInvoicesPhrase } from "./ShiftCloseDialog";

describe("heldInvoicesPhrase (Arabic number agreement)", () => {
  it.each([
    [1, "توجد فاتورة معلقة"],
    [2, "توجد فاتورتان معلقتان"],
    [3, "توجد 3 فواتير معلقة"],
    [10, "توجد 10 فواتير معلقة"],
    [11, "توجد 11 فاتورة معلقة"],
    [25, "توجد 25 فاتورة معلقة"],
  ])("%i -> %s", (n, text) => expect(heldInvoicesPhrase(n)).toBe(text));
});
