// بيانات تجريبية موحّدة لصفحات العمليات (المرتجعات، الاستبدال، الموردون، التقارير).
// كل الأرقام مشتقة من نفس بيانات النظام (الفواتير والمنتجات والأصناف) لتظهر الشاشات مترابطة.

import { allVariants, invoices, products, suppliers, topProducts } from "@/cashier/lib/mockData";

// ── سجل المرتجعات ─────────────────────────────────────────────────────────────
export const returnRecords = [
  {
    id: "ret-1",
    number: "RET-2026-0012",
    date: "2026-10-19T09:12:00",
    invoiceId: "inv-5",
    invoiceNumber: "INV-2026-0065",
    customer: "محمد عبد الرحمن",
    productName: "بنطلون جينز سليم فيت",
    variant: "أزرق فاتح / L",
    qty: 1,
    amount: 341,
    refundMethod: "cash",
    reason: "المقاس غير مناسب",
    employee: "منى عبد الله",
    status: "completed",
  },
  {
    id: "ret-2",
    number: "RET-2026-0013",
    date: "2026-10-18T17:02:00",
    invoiceId: "inv-7",
    invoiceNumber: "INV-2026-0067",
    customer: "عميل نقدي",
    productName: "بلوزة ساتان بأكمام واسعة",
    variant: "أحمر / L",
    qty: 1,
    amount: 450,
    refundMethod: "cash",
    reason: "عيب في المنتج",
    employee: "منى عبد الله",
    status: "completed",
  },
  {
    id: "ret-3",
    number: "RET-2026-0014",
    date: "2026-10-18T15:40:00",
    invoiceId: "inv-9",
    invoiceNumber: "INV-2026-0069",
    customer: "عميل نقدي",
    productName: "بنطلون قماش كاجوال",
    variant: "بيج / L",
    qty: 1,
    amount: 560,
    refundMethod: "card",
    reason: "اللون مختلف عن المتوقع",
    employee: "أحمد سمير",
    status: "completed",
  },
  {
    id: "ret-4",
    number: "RET-2026-0015",
    date: "2026-10-18T12:20:00",
    invoiceId: "inv-6",
    invoiceNumber: "INV-2026-0066",
    customer: "محمد عبد الرحمن",
    productName: "تيشيرت قطن بيما كتف عادي",
    variant: "أبيض / M",
    qty: 1,
    amount: 350,
    refundMethod: "wallet",
    reason: "المقاس غير مناسب",
    employee: "محمود فتحي",
    status: "completed",
  },
  {
    id: "ret-5",
    number: "RET-2026-0016",
    date: "2026-10-17T19:45:00",
    invoiceId: "inv-10",
    invoiceNumber: "INV-2026-0070",
    customer: "نورهان صالح",
    productName: "فستان كاجوال مشجر",
    variant: "كحلي / M",
    qty: 1,
    amount: 980,
    refundMethod: "cash",
    reason: "عيب في المنتج",
    employee: "منى عبد الله",
    status: "review",
  },
  {
    id: "ret-6",
    number: "RET-2026-0017",
    date: "2026-10-17T14:10:00",
    invoiceId: "inv-8",
    invoiceNumber: "INV-2026-0068",
    customer: "أمنية رشاد",
    productName: "بلوفر صوف رقبة دائرية",
    variant: "كحلي / M",
    qty: 1,
    amount: 558,
    refundMethod: "balance",
    reason: "العميل غيّر رأيه",
    employee: "أحمد سمير",
    status: "completed",
  },
  {
    id: "ret-7",
    number: "RET-2026-0018",
    date: "2026-10-16T18:05:00",
    invoiceId: "inv-12",
    invoiceNumber: "INV-2026-0072",
    customer: "عميل نقدي",
    productName: "بيجامة قطن قطرية",
    variant: "كحلي / L",
    qty: 3,
    amount: 1008,
    refundMethod: "cash",
    reason: "المقاس غير مناسب",
    employee: "محمود فتحي",
    status: "completed",
  },
  {
    id: "ret-8",
    number: "RET-2026-0019",
    date: "2026-10-16T13:30:00",
    invoiceId: "inv-11",
    invoiceNumber: "INV-2026-0071",
    customer: "سارة إبراهيم",
    productName: "حذاء كلاسيك جلد طبيعي",
    variant: "بني / 41",
    qty: 1,
    amount: 1064,
    refundMethod: "card",
    reason: "المقاس غير مناسب",
    employee: "منى عبد الله",
    status: "completed",
  },
  {
    id: "ret-9",
    number: "RET-2026-0020",
    date: "2026-10-15T19:20:00",
    invoiceId: "inv-13",
    invoiceNumber: "INV-2026-0073",
    customer: "كريم الديب",
    productName: "جاكيت جينز مبطن",
    variant: "كحلي / L",
    qty: 1,
    amount: 1150,
    refundMethod: "wallet",
    reason: "اللون مختلف عن المتوقع",
    employee: "أحمد سمير",
    status: "completed",
  },
  {
    id: "ret-10",
    number: "RET-2026-0021",
    date: "2026-10-13T17:10:00",
    invoiceId: "inv-16",
    invoiceNumber: "INV-2026-0076",
    customer: "أمنية رشاد",
    productName: "بلوزة ساتان بأكمام واسعة",
    variant: "أسود / L",
    qty: 2,
    amount: 810,
    refundMethod: "cash",
    reason: "عيب في المنتج",
    employee: "منى عبد الله",
    status: "completed",
  },
];

// ── سجل عمليات الاستبدال ─────────────────────────────────────────────────────
export const exchangeRecords = [
  {
    id: "exc-1",
    number: "EXC-2026-0001",
    date: "2026-10-19T10:20:00",
    invoiceId: "inv-2",
    invoiceNumber: "INV-2026-0062",
    customer: "سارة إبراهيم",
    returnedItem: "فستان كاجوال مشجر — وردي / M",
    newItem: "تيشيرت بولو بأزرار — كحلي / L",
    returnedValue: 931,
    newValue: 395,
    settlement: "refunded",
    employee: "أحمد سمير",
    status: "completed",
  },
  {
    id: "exc-2",
    number: "EXC-2026-0002",
    date: "2026-10-18T20:40:00",
    invoiceId: "inv-3",
    invoiceNumber: "INV-2026-0063",
    customer: "نورهان صالح",
    returnedItem: "حذاء رياضي خفيف — أسود / 42",
    newItem: "حذاء كلاسيك جلد طبيعي — بني / 42",
    returnedValue: 950,
    newValue: 1120,
    settlement: "collected",
    employee: "محمود فتحي",
    status: "completed",
  },
  {
    id: "exc-3",
    number: "EXC-2026-0003",
    date: "2026-10-17T16:15:00",
    invoiceId: "inv-6",
    invoiceNumber: "INV-2026-0066",
    customer: "محمد عبد الرحمن",
    returnedItem: "جاكيت جينز مبطن — كحلي / XL",
    newItem: "جاكيت جينز مبطن — أزرق فاتح / XL",
    returnedValue: 1150,
    newValue: 1150,
    settlement: "even",
    employee: "منى عبد الله",
    status: "completed",
  },
  {
    id: "exc-4",
    number: "EXC-2026-0004",
    date: "2026-10-16T18:45:00",
    invoiceId: "inv-8",
    invoiceNumber: "INV-2026-0068",
    customer: "أمنية رشاد",
    returnedItem: "بلوفر صوف رقبة دائرية — كحلي / M",
    newItem: "بلوفر صوف رقبة دائرية — بني / L",
    returnedValue: 558,
    newValue: 620,
    settlement: "collected",
    employee: "أحمد سمير",
    status: "completed",
  },
  {
    id: "exc-5",
    number: "EXC-2026-0005",
    date: "2026-10-16T12:35:00",
    invoiceId: "inv-10",
    invoiceNumber: "INV-2026-0070",
    customer: "نورهان صالح",
    returnedItem: "تيشيرت أطفال مطبوع — وردي / 6 سنوات",
    newItem: "تيشيرت أطفال مطبوع — أزرق فاتح / 8 سنوات",
    returnedValue: 180,
    newValue: 180,
    settlement: "even",
    employee: "محمود فتحي",
    status: "completed",
  },
  {
    id: "exc-6",
    number: "EXC-2026-0006",
    date: "2026-10-15T18:50:00",
    invoiceId: "inv-14",
    invoiceNumber: "INV-2026-0074",
    customer: "كريم الديب",
    returnedItem: "قميص كلاسيك كاروهات — رمادي / L",
    newItem: "جاكيت جينز مبطن — كحلي / L",
    returnedValue: 520,
    newValue: 1150,
    settlement: "collected",
    employee: "منى عبد الله",
    status: "completed",
  },
  {
    id: "exc-7",
    number: "EXC-2026-0007",
    date: "2026-10-14T17:55:00",
    invoiceId: "inv-15",
    invoiceNumber: "INV-2026-0075",
    customer: "عميل نقدي",
    returnedItem: "تيشيرت أطفال مطبوع — أزرق فاتح / 4 سنوات",
    newItem: "حزام جلد بإبزيم معدني — بني / مقاس واحد",
    returnedValue: 360,
    newValue: 180,
    settlement: "refunded",
    employee: "أحمد سمير",
    status: "completed",
  },
  {
    id: "exc-8",
    number: "EXC-2026-0008",
    date: "2026-10-13T16:40:00",
    invoiceId: "inv-16",
    invoiceNumber: "INV-2026-0076",
    customer: "أمنية رشاد",
    returnedItem: "بلوزة ساتان بأكمام واسعة — أسود / L",
    newItem: "بلوزة ساتان بأكمام واسعة — بيج / XL",
    returnedValue: 810,
    newValue: 450,
    settlement: "refunded",
    employee: "منى عبد الله",
    status: "review",
  },
];

export function settlementOf(record) {
  const difference = +(record.newValue - record.returnedValue).toFixed(2);
  return { difference, kind: difference > 0 ? "collected" : difference < 0 ? "refunded" : "even", amount: Math.abs(difference) };
}

export function returnsSummary(records = returnRecords) {
  return {
    count: records.length,
    amount: +records.reduce((s, r) => s + r.amount, 0).toFixed(2),
    qty: records.reduce((s, r) => s + r.qty, 0),
    review: records.filter((r) => r.status === "review").length,
  };
}

export function exchangesSummary(records = exchangeRecords) {
  const totals = records.reduce(
    (acc, r) => {
      const { difference } = settlementOf(r);
      return {
        newValue: acc.newValue + r.newValue,
        collected: acc.collected + (difference > 0 ? difference : 0),
        refunded: acc.refunded + (difference < 0 ? Math.abs(difference) : 0),
        even: acc.even + (difference === 0 ? 1 : 0),
      };
    },
    { newValue: 0, collected: 0, refunded: 0, even: 0 },
  );
  return {
    count: records.length,
    newValue: +totals.newValue.toFixed(2),
    net: +(totals.collected - totals.refunded).toFixed(2),
    even: totals.even,
    review: records.filter((r) => r.status === "review").length,
  };
}

// ── الموردون ─────────────────────────────────────────────────────────────────
const SUPPLIER_EXTRA = {
  "s-1": { agent: "أيمن خليل", city: "القاهرة", items: 34, status: "active" },
  "s-2": { agent: "سامي عبد الحكيم", city: "المحلة الكبرى", items: 22, status: "active" },
  "s-3": { agent: "رامي شعبان", city: "القاهرة", items: 18, status: "active" },
  "s-4": { agent: "ليلى محسن", city: "الإسكندرية", items: 41, status: "active" },
  "s-5": { agent: "هاني درويش", city: "الجيزة", items: 26, status: "inactive" },
};

export const supplierRows = suppliers.map((s) => ({ ...s, ...SUPPLIER_EXTRA[s.id] }));
export const supplierCities = [...new Set(supplierRows.map((s) => s.city))];

export function suppliersSummary(rows = supplierRows) {
  return {
    count: rows.length,
    total: rows.reduce((s, r) => s + r.total, 0),
    balance: rows.reduce((s, r) => s + r.balance, 0),
    lastDeal: rows.map((r) => r.lastDeal).sort().slice(-1)[0],
    late: rows.filter((r) => r.balance > 0).length,
  };
}

// ── جداول التقارير ───────────────────────────────────────────────────────────
function referenceDay() {
  const days = invoices.map((i) => i.date.slice(0, 10)).sort();
  return days[days.length - 1];
}

const PERIOD_DAYS = { today: 1, "7d": 7, "30d": 30 };
export const PERIODS = [
  { key: "today", label: "اليوم" },
  { key: "7d", label: "آخر ٧ أيام" },
  { key: "30d", label: "آخر ٣٠ يومًا" },
];

// تقرير المبيعات اليومية: مجمّع من الفواتير الفعلية ثم مطروحًا منه المرتجعات المسجلة في نفس اليوم.
// حدود الفترة المختارة (نفس نقطة المرجع التي تستخدمها تقارير المبيعات) لتوحيد الفلترة بين التقارير.
export function inPeriod(isoDate, period = "7d") {
  const days = PERIOD_DAYS[period] ?? 7;
  const ref = new Date(`${referenceDay()}T00:00:00`);
  const cutoff = new Date(ref);
  cutoff.setDate(cutoff.getDate() - (days - 1));
  const d = new Date(`${String(isoDate).slice(0, 10)}T00:00:00`);
  return d >= cutoff && d <= ref;
}

export function dailySalesRows(period = "7d") {
  const days = PERIOD_DAYS[period] ?? 7;
  const ref = new Date(`${referenceDay()}T00:00:00`);
  const cutoff = new Date(ref);
  cutoff.setDate(cutoff.getDate() - (days - 1));

  const map = new Map();
  invoices
    .filter((inv) => inv.status !== "suspended")
    .forEach((inv) => {
      const day = inv.date.slice(0, 10);
      if (new Date(`${day}T00:00:00`) < cutoff) return;
      const row = map.get(day) ?? { id: day, date: day, invoices: 0, pieces: 0, gross: 0, discount: 0, returns: 0, net: 0 };
      row.invoices += 1;
      row.pieces += inv.pieces;
      row.gross += inv.subTotal;
      row.discount += inv.discount;
      row.net += inv.total;
      map.set(day, row);
    });

  returnRecords.forEach((r) => {
    const row = map.get(r.date.slice(0, 10));
    if (row) row.returns += r.amount;
  });

  return [...map.values()]
    .map((r) => ({
      ...r,
      gross: +r.gross.toFixed(2),
      discount: +r.discount.toFixed(2),
      returns: +r.returns.toFixed(2),
      net: +(r.net - r.returns).toFixed(2),
    }))
    .sort((a, b) => (a.date < b.date ? 1 : -1));
}

// الأصناف الأكثر مبيعًا مع التكلفة والربح الفعلي لكل صنف.
export const topProductRows = topProducts.map((tp) => {
  const product = products.find((p) => p.id === tp.id);
  const cost = +(product.buyPrice * tp.qty).toFixed(2);
  const profit = +(tp.revenue - cost).toFixed(2);
  return {
    ...tp,
    sku: product.sku,
    cost,
    profit,
    margin: +((profit / tp.revenue) * 100).toFixed(1),
  };
});

// تقرير المرتجعات: مجمّع حسب سبب الإرجاع مع نسبة كل سبب من إجمالي المرتجعات.
export const returnsReportRows = (() => {
  const map = new Map();
  returnRecords.forEach((r) => {
    const row = map.get(r.reason) ?? { id: r.reason, reason: r.reason, count: 0, qty: 0, amount: 0, invoices: new Set() };
    row.count += 1;
    row.qty += r.qty;
    row.amount += r.amount;
    row.invoices.add(r.invoiceNumber);
    map.set(r.reason, row);
  });

  const rows = [...map.values()]
    .map((r) => ({ ...r, invoices: r.invoices.size, amount: +r.amount.toFixed(2), average: +(r.amount / r.count).toFixed(2) }))
    .sort((a, b) => b.amount - a.amount);
  const total = rows.reduce((s, r) => s + r.amount, 0);
  return rows.map((r) => ({ ...r, share: total ? +((r.amount / total) * 100).toFixed(1) : 0 }));
})();

// تقرير الأرباح حسب تصنيف المنتج (يساوي إجمالي تقرير الأرباح العام).
export const categoryProfitRows = [
  { id: "c-1", category: "تيشيرتات", pieces: 96, revenue: 32400, cost: 17100 },
  { id: "c-2", category: "بناطيل", pieces: 62, revenue: 38250, cost: 21100 },
  { id: "c-3", category: "فساتين", pieces: 28, revenue: 24600, cost: 13750 },
  { id: "c-4", category: "قمصان", pieces: 34, revenue: 18240, cost: 9650 },
  { id: "c-5", category: "بلوزات", pieces: 38, revenue: 16800, cost: 9100 },
  { id: "c-6", category: "جواكت", pieces: 14, revenue: 15600, cost: 10300 },
  { id: "c-7", category: "أحذية", pieces: 16, revenue: 14280, cost: 8300 },
  { id: "c-8", category: "أطفال", pieces: 52, revenue: 8640, cost: 4900 },
  { id: "c-9", category: "ملابس نوم", pieces: 22, revenue: 5110, cost: 3040 },
  { id: "c-10", category: "إكسسوارات", pieces: 16, revenue: 2500, cost: 1400 },
].map((r) => ({ ...r, profit: +(r.revenue - r.cost).toFixed(2), margin: +(((r.revenue - r.cost) / r.revenue) * 100).toFixed(1) }));

// تقييم المخزون: قيمة الأرصدة الفعلية على مستوى التصنيف.
export const inventoryValueRows = (() => {
  const map = new Map();
  allVariants.forEach((v) => {
    const row = map.get(v.category) ?? { id: v.category, category: v.category, items: new Set(), variants: 0, pieces: 0, cost: 0, retail: 0 };
    row.items.add(v.productId);
    row.variants += 1;
    row.pieces += v.stock;
    row.cost += v.buyPrice * v.stock;
    row.retail += v.sellPrice * v.stock;
    map.set(v.category, row);
  });
  return [...map.values()]
    .map((r) => ({ ...r, items: r.items.size, cost: +r.cost.toFixed(2), retail: +r.retail.toFixed(2), margin: r.retail ? +(((r.retail - r.cost) / r.retail) * 100).toFixed(1) : 0 }))
    .sort((a, b) => b.retail - a.retail);
})();