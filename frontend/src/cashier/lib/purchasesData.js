// بيانات فواتير التوريد (المشتريات): البضاعة الداخلة للمحل وتكاليف شرائها.
// مشتقة من نفس كتالوج المنتجات والموردين لتظهر الشاشات مترابطة.

import { allVariants, suppliers } from "@/cashier/lib/mockData";

function variantOf(productId, color, size) {
  const exact = allVariants.find((v) => v.productId === productId && v.color === color && v.size === size);
  return exact ?? allVariants.find((v) => v.productId === productId);
}

function line(productId, color, size, qty, unitCost) {
  const v = variantOf(productId, color, size);
  const cost = unitCost ?? v.buyPrice;
  return { name: v.productName, color: v.color, size: v.size, qty, unitCost: cost, total: +(cost * qty).toFixed(2) };
}

function order(index, config) {
  const items = config.items;
  const total = +items.reduce((s, i) => s + i.total, 0).toFixed(2);
  const paid = config.paid ?? total;
  return {
    id: `po-${index + 1}`,
    number: `PO-2026-${String(118 + index).padStart(4, "0")}`,
    date: config.date,
    supplierId: config.supplierId,
    supplierName: suppliers.find((s) => s.id === config.supplierId)?.name ?? "—",
    items,
    pieces: items.reduce((s, i) => s + i.qty, 0),
    total,
    paid: +paid.toFixed(2),
    balance: +(total - paid).toFixed(2),
    warehouse: config.warehouse ?? "المخزن الرئيسي",
    employee: config.employee ?? "منى عبد الله",
    status: config.status ?? (paid >= total ? "received" : paid > 0 ? "partial" : "pending"),
    note: config.note ?? "",
  };
}

export const purchaseOrders = [
  order(0, {
    date: "2026-10-16T10:20:00",
    supplierId: "s-1",
    items: [line("p-1", "أسود", "L", 12), line("p-1", "كحلي", "M", 10), line("p-8", "أبيض", "L", 8)],
    paid: 6000,
    employee: "منى عبد الله",
  }),
  order(1, {
    date: "2026-10-15T09:40:00",
    supplierId: "s-4",
    items: [line("p-5", "وردي", "M", 6), line("p-7", "كحلي", "XL", 4), line("p-13", "رمادي", "L", 8)],
    paid: 9000,
    note: "شحنة استيراد — الشحن على المورد",
  }),
  order(2, {
    date: "2026-10-13T11:05:00",
    supplierId: "s-2",
    items: [line("p-4", "بيج", "L", 10), line("p-14", "كحلي", "L", 12), line("p-6", "أحمر", "M", 6)],
    employee: "محمود فتحي",
  }),
  order(3, {
    date: "2026-10-11T08:30:00",
    supplierId: "s-3",
    items: [line("p-9", "أسود", "42", 8), line("p-10", "بني", "41", 6), line("p-11", "بني", "مقاس واحد", 20)],
    paid: 5000,
  }),
  order(4, {
    date: "2026-10-09T12:15:00",
    supplierId: "s-5",
    items: [line("p-12", "وردي", "4 سنوات", 14), line("p-12", "أزرق فاتح", "6 سنوات", 12)],
    status: "received",
  }),
  order(5, {
    date: "2026-10-06T10:50:00",
    supplierId: "s-1",
    items: [line("p-3", "كحلي", "L", 10), line("p-3", "أزرق فاتح", "M", 8)],
    employee: "منى عبد الله",
  }),
  order(6, {
    date: "2026-10-03T09:10:00",
    supplierId: "s-4",
    items: [line("p-2", "أبيض", "XL", 10), line("p-13", "كحلي", "M", 6)],
    paid: 3500,
    warehouse: "المعرض",
  }),
  order(7, {
    date: "2026-09-29T13:25:00",
    supplierId: "s-5",
    items: [line("p-12", "أبيض", "2 سنة", 10), line("p-12", "وردي", "8 سنوات", 6)],
    status: "received",
    employee: "محمود فتحي",
  }),
];

export const PURCHASE_STATUSES = [
  { key: "received", label: "مستلم" },
  { key: "partial", label: "مدفوع جزئيًا" },
  { key: "pending", label: "قيد التنفيذ" },
];

export function purchasesSummary(rows = purchaseOrders) {
  return {
    count: rows.length,
    total: +rows.reduce((s, r) => s + r.total, 0).toFixed(2),
    paid: +rows.reduce((s, r) => s + r.paid, 0).toFixed(2),
    balance: +rows.reduce((s, r) => s + r.balance, 0).toFixed(2),
    pieces: rows.reduce((s, r) => s + r.pieces, 0),
    pending: rows.filter((r) => r.status !== "received").length,
  };
}

export function supplierPurchases(supplierId) {
  return purchaseOrders.filter((o) => o.supplierId === supplierId);
}