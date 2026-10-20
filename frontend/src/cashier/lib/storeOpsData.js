// بيانات تجريبية للوحدات الجديدة: مرتجعات الموردين، الورديات والخزنة، المصروفات، وتقرير المشتريات.
// كل الأرقام مشتقة من بيانات النظام نفسه (الفواتير، المرتجعات، المصروفات، فواتير التوريد).

import { allVariants, expenses, invoices, shop, suppliers } from "@/cashier/lib/mockData";
import { returnRecords } from "@/cashier/lib/opsData";
import { purchaseOrders } from "@/cashier/lib/purchasesData";

const day = (iso) => String(iso).slice(0, 10);

// ── مرتجعات الموردين ─────────────────────────────────────────────────────────
function variantOf(productName, color, size) {
  return (
    allVariants.find((v) => v.productName === productName && v.color === color && v.size === size) ??
    allVariants.find((v) => v.productName === productName)
  );
}

function supplierReturn(index, config) {
  const v = variantOf(config.product, config.color, config.size);
  const unitCost = config.unitCost ?? v.buyPrice;
  return {
    id: `sr-${index + 1}`,
    number: `SR-2026-${String(101 + index).padStart(4, "0")}`,
    date: config.date,
    supplierId: config.supplierId,
    supplierName: suppliers.find((s) => s.id === config.supplierId)?.name ?? "—",
    poNumber: config.poNumber,
    productName: v.productName,
    sku: v.sku,
    color: v.color,
    size: v.size,
    qty: config.qty,
    unitCost,
    amount: +(unitCost * config.qty).toFixed(2),
    reason: config.reason,
    settlement: config.settlement,
    status: config.status ?? "completed",
    employee: config.employee ?? "منى عبد الله",
    note: config.note ?? "",
  };
}

export const supplierReturnRecords = [
  supplierReturn(0, {
    date: "2026-10-19T12:05:00",
    supplierId: "s-1",
    poNumber: "PO-2026-0118",
    product: "تيشيرت قطن بيما كتف عادي",
    color: "كحلي",
    size: "S",
    qty: 2,
    reason: "فائض عن الحاجة",
    settlement: "credit",
    status: "review",
    note: "بانتظار موافقة المورد على الخصم",
  }),
  supplierReturn(1, {
    date: "2026-10-18T16:20:00",
    supplierId: "s-1",
    poNumber: "PO-2026-0118",
    product: "قميص كلاسيك كاروهات",
    color: "أبيض",
    size: "XL",
    qty: 3,
    reason: "عيب تصنيع",
    settlement: "credit",
    employee: "منى عبد الله",
  }),
  supplierReturn(2, {
    date: "2026-10-17T13:40:00",
    supplierId: "s-4",
    poNumber: "PO-2026-0119",
    product: "بلوزة ساتان بأكمام واسعة",
    color: "أحمر",
    size: "M",
    qty: 2,
    reason: "لون مختلف عن المعروض",
    settlement: "cash",
    employee: "أحمد سمير",
  }),
  supplierReturn(3, {
    date: "2026-10-15T11:10:00",
    supplierId: "s-3",
    poNumber: "PO-2026-0121",
    product: "حذاء كلاسيك جلد طبيعي",
    color: "بني",
    size: "41",
    qty: 1,
    reason: "خامة أقل من الاتفاق",
    settlement: "replace",
    employee: "محمود فتحي",
    note: "سيتم استبدالها بشحنة الأسبوع القادم",
  }),
  supplierReturn(4, {
    date: "2026-10-12T17:25:00",
    supplierId: "s-2",
    poNumber: "PO-2026-0120",
    product: "بنطلون قماش كاجوال",
    color: "بيج",
    size: "L",
    qty: 4,
    reason: "مقاسات خاطئة من المورد",
    settlement: "credit",
    employee: "منى عبد الله",
  }),
  supplierReturn(5, {
    date: "2026-10-09T10:35:00",
    supplierId: "s-5",
    poNumber: "PO-2026-0122",
    product: "تيشيرت أطفال مطبوع",
    color: "وردي",
    size: "4 سنوات",
    qty: 6,
    reason: "بضاعة تالفة عند الاستلام",
    settlement: "cash",
    employee: "محمود فتحي",
  }),
];

export function supplierReturnsSummary(rows = supplierReturnRecords) {
  return {
    count: rows.length,
    qty: rows.reduce((s, r) => s + r.qty, 0),
    amount: +rows.reduce((s, r) => s + r.amount, 0).toFixed(2),
    cash: +rows.filter((r) => r.settlement === "cash").reduce((s, r) => s + r.amount, 0).toFixed(2),
    credit: +rows.filter((r) => r.settlement === "credit").reduce((s, r) => s + r.amount, 0).toFixed(2),
    review: rows.filter((r) => r.status === "review").length,
    suppliersCount: new Set(rows.map((r) => r.supplierId)).size,
  };
}

// أثر المرتجعات على حساب المورد: البضاعة المرتجعة تُخصم من المديونية (تسوية: خصم من الحساب).
export function supplierReturnsForSupplier(supplierId) {
  return supplierReturnRecords.filter((r) => r.supplierId === supplierId);
}

export function supplierReturnCredit(supplierId) {
  return +supplierReturnRecords
    .filter((r) => r.supplierId === supplierId && r.settlement === "credit")
    .reduce((s, r) => s + r.amount, 0)
    .toFixed(2);
}

// ── الورديات والخزنة ─────────────────────────────────────────────────────────
function dayFigures(dateStr) {
  const dayInvoices = invoices.filter((i) => day(i.date) === dateStr && i.status !== "suspended");
  const byMethod = (m) => +dayInvoices.filter((i) => i.payment === m).reduce((s, i) => s + i.total, 0).toFixed(2);

  return {
    invoices: dayInvoices.length,
    pieces: dayInvoices.reduce((s, i) => s + i.pieces, 0),
    cashSales: byMethod("cash"),
    nonCashSales: +(byMethod("card") + byMethod("wallet") + byMethod("credit")).toFixed(2),
    returnsCash: +returnRecords
      .filter((r) => day(r.date) === dateStr && r.refundMethod === "cash")
      .reduce((s, r) => s + r.amount, 0)
      .toFixed(2),
    expensesCash: +expenses
      .filter((e) => day(e.date) === dateStr && e.payment === "cash")
      .reduce((s, e) => s + e.amount, 0)
      .toFixed(2),
  };
}

function makeShift(index, config) {
  return {
    id: `sh-${index + 1}`,
    number: `SH-2026-${String(41 - index).padStart(4, "0")}`,
    date: `${config.date}T09:00:00`,
    branch: shop.branch,
    employee: config.employee,
    openingCash: config.openingCash,
    ...dayFigures(config.date),
    variance: config.variance ?? 0,
    closedAt: config.closedAt ?? null,
    status: config.closedAt ? "closed" : "open",
    note: config.note ?? "",
  };
}

export const shiftRecords = [
  makeShift(0, { date: "2026-10-19", employee: "أحمد سمير", openingCash: 1500, note: "الوردية الصباحية — مفتوحة الآن" }),
  makeShift(1, { date: "2026-10-18", employee: "محمود فتحي", openingCash: 1200, variance: 35, closedAt: "2026-10-18T22:10:00", note: "فرق زيادة عند العدّ" }),
  makeShift(2, { date: "2026-10-17", employee: "أحمد سمير", openingCash: 1500, variance: -20, closedAt: "2026-10-17T22:05:00", note: "عجز بسيط في النقدية" }),
  makeShift(3, { date: "2026-10-16", employee: "منى عبد الله", openingCash: 2000, variance: 0, closedAt: "2026-10-16T21:50:00", note: "الخزنة مطابقة" }),
];

export function shiftExpected(shift) {
  return +(shift.openingCash + shift.cashSales - shift.returnsCash - shift.expensesCash).toFixed(2);
}

export function shiftRow(shift) {
  const expected = shiftExpected(shift);
  const actual = shift.status === "closed" ? +(expected + (shift.variance ?? 0)).toFixed(2) : null;
  return {
    ...shift,
    otherSales: shift.nonCashSales,
    expected,
    actual,
    difference: actual == null ? 0 : +(actual - expected).toFixed(2),
  };
}

export const shiftRows = shiftRecords.map(shiftRow);

export function shiftsSummary(rows = shiftRows) {
  const open = rows.find((r) => r.status === "open") ?? null;
  const closed = rows.filter((r) => r.status === "closed");
  return {
    open,
    count: rows.length,
    closedCount: closed.length,
    cashSales: +rows.reduce((s, r) => s + r.cashSales, 0).toFixed(2),
    differences: +closed.reduce((s, r) => s + Math.abs(r.difference), 0).toFixed(2),
    collected: +closed.reduce((s, r) => s + r.actual, 0).toFixed(2),
  };
}

// ── المصروفات ────────────────────────────────────────────────────────────────
export const EXPENSE_CATEGORIES = [
  "مستلزمات تغليف",
  "نقل وشحن",
  "إنترنت واتصالات",
  "كهرباء ومياه",
  "تسويق وإعلانات",
  "صيانة",
  "رواتب",
  "نظافة",
  "إيجار",
  "مصاريف إدارية",
  "أخرى",
];

export const EXPENSE_PAYMENTS = ["cash", "card", "wallet"];

export const expenseRows = [
  ...expenses,
  {
    id: "ex-9",
    number: "EXP-1033",
    date: "2026-10-15T11:00:00",
    category: "إيجار",
    description: "إيجار المحل — أكتوبر",
    amount: 12000,
    payment: "cash",
    employee: "منى عبد الله",
  },
  {
    id: "ex-10",
    number: "EXP-1032",
    date: "2026-10-14T09:30:00",
    category: "مصاريف إدارية",
    description: "رسوم تجديد السجل التجاري",
    amount: 400,
    payment: "card",
    employee: "منى عبد الله",
  },
].sort((a, b) => new Date(b.date) - new Date(a.date));

export function expensesSummary(rows = expenseRows) {
  const today = "2026-10-19";
  const byCategory = new Map();
  rows.forEach((e) => byCategory.set(e.category, (byCategory.get(e.category) ?? 0) + e.amount));
  const top = [...byCategory.entries()].sort((a, b) => b[1] - a[1])[0] ?? ["—", 0];

  return {
    count: rows.length,
    total: +rows.reduce((s, e) => s + e.amount, 0).toFixed(2),
    today: +rows.filter((e) => day(e.date) === today).reduce((s, e) => s + e.amount, 0).toFixed(2),
    cash: +rows.filter((e) => e.payment === "cash").reduce((s, e) => s + e.amount, 0).toFixed(2),
    top: top[0],
    topAmount: +top[1].toFixed(2),
  };
}

// ── تقرير المشتريات ──────────────────────────────────────────────────────────
export const purchasesReportRows = suppliers
  .map((s) => {
    const orders = purchaseOrders.filter((o) => o.supplierId === s.id);
    const total = +orders.reduce((x, o) => x + o.total, 0).toFixed(2);
    const paid = +orders.reduce((x, o) => x + o.paid, 0).toFixed(2);
    return {
      id: s.id,
      supplier: s.name,
      orders: orders.length,
      pieces: orders.reduce((x, o) => x + o.pieces, 0),
      total,
      paid,
      balance: +(total - paid).toFixed(2),
      lastOrder: orders.map((o) => day(o.date)).sort().slice(-1)[0] ?? null,
    };
  })
  .sort((a, b) => b.total - a.total);