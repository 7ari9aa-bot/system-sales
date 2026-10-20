// سجل العمليات: كل حركات النظام (بيع، مرتجع، استبدال، توريد، مرتجع مورد، مصروفات، مخزون، ورديات)
// في خط زمني واحد مشتق من بيانات الشاشات نفسها.

import { invoices, shop, stockMovements } from "@/cashier/lib/mockData";
import { exchangeRecords, returnRecords } from "@/cashier/lib/opsData";
import { purchaseOrders } from "@/cashier/lib/purchasesData";
import { expenseRows, shiftExpected, shiftRecords, supplierReturnRecords } from "@/cashier/lib/storeOpsData";
import { MOVEMENT_TYPES, fmtMoney } from "@/cashier/lib/format";

function entry(type, date, doc, details, employee, branch) {
  return { id: `${type}-${doc}-${date}`, type, date, doc, details, employee, branch: branch ?? shop.branch };
}

const entries = [
  ...invoices.map((i) =>
    entry(
      i.status === "suspended" ? "sale_hold" : "sale",
      i.date,
      i.number,
      `فاتورة بيع ${i.pieces} قطعة بمبلغ ${fmtMoney(i.total)} — ${i.customerName}`,
      i.cashier,
    ),
  ),
  ...returnRecords.map((r) => entry("return", r.date, r.number, `مرتجع عميل: ${r.productName} (${r.qty} قطعة) — ${r.reason}`, r.employee)),
  ...exchangeRecords.map((r) => entry("exchange", r.date, r.number, `استبدال: ${r.returnedItem} ↔ ${r.newItem}`, r.employee)),
  ...purchaseOrders.map((o) => entry("purchase", o.date, o.number, `توريد ${o.pieces} قطعة من ${o.supplierName} بمبلغ ${fmtMoney(o.total)}`, o.employee, o.warehouse)),
  ...supplierReturnRecords.map((r) => entry("supplier_return", r.date, r.number, `إرجاع للمورد ${r.supplierName}: ${r.productName} (${r.qty} قطعة) — ${r.reason}`, r.employee)),
  ...expenseRows.map((e) => entry("expense", e.date, e.number, `مصروف ${e.category}: ${e.description} — ${fmtMoney(e.amount)}`, e.employee)),
  ...stockMovements.map((m) =>
    entry(
      "inventory",
      m.date,
      m.doc,
      `${MOVEMENT_TYPES[m.type]?.label ?? m.type}: ${m.productName} (${m.variant}) ${m.qtyIn > 0 ? `+${m.qtyIn}` : `−${m.qtyOut}`} قطعة`,
      m.employee,
    ),
  ),
  ...shiftRecords.map((s) => entry("shift", s.date, s.number, `فتح وردية برصيد ${fmtMoney(s.openingCash)}`, s.employee)),
  ...shiftRecords
    .filter((s) => s.closedAt)
    .map((s) => entry("shift", s.closedAt, s.number, `إغلاق وردية — النقدية المتوقعة ${fmtMoney(shiftExpected(s))}`, s.employee)),
];

export const activityRows = entries.sort((a, b) => new Date(b.date) - new Date(a.date));

export function activitySummary(rows = activityRows) {
  const today = "2026-10-19";
  return {
    count: rows.length,
    today: rows.filter((r) => r.date.slice(0, 10) === today).length,
    employees: new Set(rows.map((r) => r.employee)).size,
    last: rows[0] ?? null,
  };
}