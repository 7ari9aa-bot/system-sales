// بيانات تجريبية واقعية للنموذج البصري (نظام مبيعات محلات ملابس - الجنيه المصري).
// لا يوجد اتصال بقاعدة بيانات: كل الأرقام مُشتقة بشكل ثابت لتظهر الشاشات ببيانات مترابطة.

export const shop = {
  name: "بوتيك النخبة",
  branch: "الفرع الرئيسي — مدينة نصر",
  address: "٤٢ شارع عباس العقاد، مدينة نصر، القاهرة",
  phone: "0226 741 890",
  taxId: "٥٥٤-٨٧٢-٣٤٩",
  currency: "ج.م",
  lowStockThreshold: 5,
};

export const employees = [
  { id: "emp-1", name: "أحمد سمير", username: "ahmed.s", job: "كاشير", role: "كاشير", status: "active", lastActive: "2026-10-19T11:52:00" },
  { id: "emp-2", name: "منى عبد الله", username: "mona.a", job: "مدير فرع", role: "مدير", status: "active", lastActive: "2026-10-19T11:40:00" },
  { id: "emp-3", name: "محمود فتحي", username: "mahmoud.f", job: "بائع", role: "بائع", status: "active", lastActive: "2026-10-19T10:58:00" },
  { id: "emp-4", name: "هبة مصطفى", username: "heba.m", job: "بائع", role: "بائع", status: "inactive", lastActive: "2026-10-12T19:20:00" },
];

export const categories = ["تيشيرتات", "قمصان", "بناطيل", "بلوزات", "فساتين", "جواكت", "أحذية", "أطفال", "ملابس نوم", "إكسسوارات"];
export const brands = ["كوتون", "أوريجينال", "دينم كو", "كوتونيل", "ستايل هاوس", "سبورت لاين", "ليدر ستايل", "كيدز وورلد"];

export const COLORS = [
  { name: "أسود", hex: "#18181B" },
  { name: "أبيض", hex: "#F4F4F5" },
  { name: "كحلي", hex: "#1E3A8A" },
  { name: "أزرق فاتح", hex: "#60A5FA" },
  { name: "رمادي", hex: "#6B7280" },
  { name: "بيج", hex: "#D6C3A5" },
  { name: "أحمر", hex: "#B91C1C" },
  { name: "أخضر زيتي", hex: "#4D7C0F" },
  { name: "وردي", hex: "#F472B6" },
  { name: "بني", hex: "#78350F" },
];

export const SIZE_SETS = {
  clothing: ["S", "M", "L", "XL", "XXL"],
  kids: ["2 سنة", "4 سنوات", "6 سنوات", "8 سنوات"],
  shoes: ["39", "40", "41", "42", "43"],
  one: ["مقاس واحد"],
};

export function colorHex(name) {
  return COLORS.find((c) => c.name === name)?.hex ?? "#A1A1AA";
}

function seedRand(seed) {
  let s = seed * 9301 + 49297;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

const PRODUCT_SEED = [
  { name: "تيشيرت قطن بيما كتف عادي", category: "تيشيرتات", brand: "كوتون", buy: 180, sell: 350, colors: ["أسود", "أبيض", "كحلي"], sizes: "clothing", low: ["كحلي|S"] },
  { name: "قميص كلاسيك كاروهات", category: "قمصان", brand: "أوريجينال", buy: 260, sell: 520, colors: ["أزرق فاتح", "أبيض", "رمادي"], sizes: "clothing", out: ["أبيض|XL"] },
  { name: "بنطلون جينز سليم فيت", category: "بناطيل", brand: "دينم كو", buy: 380, sell: 690, colors: ["كحلي", "أزرق فاتح", "أسود"], sizes: "clothing", low: ["أسود|M", "أزرق فاتح|XL"] },
  { name: "بنطلون قماش كاجوال", category: "بناطيل", brand: "كوتونيل", buy: 300, sell: 560, colors: ["بيج", "رمادي", "أسود"], sizes: "clothing" },
  { name: "فستان كاجوال مشجر", category: "فساتين", brand: "ستايل هاوس", buy: 520, sell: 980, colors: ["وردي", "كحلي"], sizes: "clothing", low: ["وردي|S"] },
  { name: "بلوزة ساتان بأكمام واسعة", category: "بلوزات", brand: "ستايل هاوس", buy: 240, sell: 450, colors: ["أحمر", "بيج", "أسود"], sizes: "clothing", out: ["أحمر|M"] },
  { name: "جاكيت جينز مبطن", category: "جواكت", brand: "دينم كو", buy: 620, sell: 1150, colors: ["كحلي", "أزرق فاتح"], sizes: "clothing" },
  { name: "تيشيرت بولو بأزرار", category: "تيشيرتات", brand: "كوتون", buy: 210, sell: 395, colors: ["أخضر زيتي", "أسود", "أبيض"], sizes: "clothing" },
  { name: "حذاء رياضي خفيف", category: "أحذية", brand: "سبورت لاين", buy: 550, sell: 950, colors: ["أسود", "أبيض"], sizes: "shoes", low: ["أبيض|43"] },
  { name: "حذاء كلاسيك جلد طبيعي", category: "أحذية", brand: "ليدر ستايل", buy: 640, sell: 1120, colors: ["بني", "أسود"], sizes: "shoes" },
  { name: "حزام جلد بإبزيم معدني", category: "إكسسوارات", brand: "ليدر ستايل", buy: 90, sell: 180, colors: ["بني", "أسود"], sizes: "one" },
  { name: "تيشيرت أطفال مطبوع", category: "أطفال", brand: "كيدز وورلد", buy: 95, sell: 180, colors: ["أزرق فاتح", "وردي", "أبيض"], sizes: "kids", low: ["وردي|4 سنوات"] },
  { name: "بلوفر صوف رقبة دائرية", category: "بلوزات", brand: "أوريجينال", buy: 340, sell: 620, colors: ["رمادي", "كحلي", "بني"], sizes: "clothing" },
  { name: "بيجامة قطن قطرية", category: "ملابس نوم", brand: "كوتون", buy: 230, sell: 420, colors: ["كحلي", "رمادي"], sizes: "clothing", out: ["رمادي|XXL"] },
];

export const products = PRODUCT_SEED.map((p, index) => {
  const id = index + 1;
  const sizes = SIZE_SETS[p.sizes];
  const sku = `SKU-${String(id).padStart(4, "0")}`;
  const rand = seedRand(id);
  const variants = [];
  p.colors.forEach((color, ci) => {
    sizes.forEach((size, si) => {
      const key = `${color}|${size}`;
      let stock = Math.floor(rand() * 16) + 7;
      if (p.out?.includes(key)) stock = 0;
      else if (p.low?.includes(key)) stock = 1 + Math.floor(rand() * 3);
      else if (rand() > 0.86) stock = Math.floor(rand() * 4) + 1;
      variants.push({
        id: `${sku}-${ci + 1}${si + 1}`,
        productId: `p-${id}`,
        productName: p.name,
        color,
        size,
        sku: `${sku}-${String(ci + 1).padStart(2, "0")}${String(si + 1).padStart(2, "0")}`,
        barcode: String(2000000010000 + id * 1000 + ci * 100 + si),
        stock,
        buyPrice: p.buy,
        sellPrice: p.sell,
      });
    });
  });
  const totalStock = variants.reduce((s, v) => s + v.stock, 0);
  return {
    id: `p-${id}`,
    sku,
    barcode: String(2000000010000 + id * 1000),
    name: p.name,
    category: p.category,
    brand: p.brand,
    description: `${p.name} — خامة عالية الجودة، مناسب للاستخدام اليومي. متوفر بجميع المقاسات.`,
    buyPrice: p.buy,
    sellPrice: p.sell,
    threshold: shop.lowStockThreshold,
    status: id === 14 ? "inactive" : "active",
    variants,
    variantsCount: variants.length,
    totalStock,
    colors: p.colors,
    sizes,
    seed: id,
  };
});

export const allVariants = products.flatMap((p) =>
  p.variants.map((v) => ({
    ...v,
    category: p.category,
    brand: p.brand,
    threshold: p.threshold,
    productStatus: p.status,
    branch: Number(v.barcode.slice(-2)) % 5 === 0 ? "المعرض" : "المخزن الرئيسي",
  })),
);

export const branches = ["المخزن الرئيسي", "المعرض"];

export function stockStatus(qty, threshold = shop.lowStockThreshold) {
  if (qty <= 0) return "out";
  if (qty <= threshold) return "low";
  return "in";
}

export function findProductByBarcode(code) {
  const clean = String(code || "").trim();
  if (!clean) return null;
  const variant = allVariants.find((v) => v.barcode === clean);
  if (variant) {
    const product = products.find((p) => p.id === variant.productId);
    return { product, variant };
  }
  const product = products.find((p) => p.barcode === clean);
  if (product) {
    const best = product.variants.find((v) => v.stock > 0) || product.variants[0];
    return { product, variant: best };
  }
  return null;
}

export function searchProducts(term, limit = 8) {
  const q = String(term || "").trim().toLowerCase();
  if (!q) return [];
  return products
    .filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.sku.toLowerCase().includes(q) ||
        p.barcode.includes(q) ||
        p.brand.toLowerCase().includes(q) ||
        p.variants.some((v) => v.barcode.includes(q) || v.sku.toLowerCase().includes(q)),
    )
    .slice(0, limit);
}

export function searchVariants(term, limit = 20) {
  const q = String(term || "").trim().toLowerCase();
  if (!q) return [];
  return allVariants
    .filter(
      (v) =>
        v.productName.toLowerCase().includes(q) ||
        v.sku.toLowerCase().includes(q) ||
        v.barcode.includes(q) ||
        v.color.includes(q) ||
        v.brand.toLowerCase().includes(q),
    )
    .slice(0, limit);
}

export const customers = [
  { id: "c-1", name: "سارة إبراهيم", phone: "0100 245 8871", invoices: 14, total: 12840, lastPurchase: "2026-10-19T11:24:00", balance: 0 },
  { id: "c-2", name: "محمد عبد الرحمن", phone: "0111 902 3345", invoices: 9, total: 9640, lastPurchase: "2026-10-18T18:12:00", balance: 400 },
  { id: "c-3", name: "نورهان صالح", phone: "0122 774 1180", invoices: 21, total: 21350, lastPurchase: "2026-10-19T10:05:00", balance: 0 },
  { id: "c-4", name: "كريم الديب", phone: "0106 331 7742", invoices: 6, total: 5210, lastPurchase: "2026-10-15T13:40:00", balance: 0 },
  { id: "c-5", name: "أمنية رشاد", phone: "0128 559 0034", invoices: 11, total: 8730, lastPurchase: "2026-10-17T20:30:00", balance: 250 },
  { id: "c-6", name: "عميل نقدي", phone: "—", invoices: 34, total: 18760, lastPurchase: "2026-10-19T11:52:00", balance: 0 },
];

export const suppliers = [
  { id: "s-1", name: "شركة النيل للملابس الجاهزة", company: "توريد جملة", phone: "0224 118 776", total: 148500, balance: 18400, lastDeal: "2026-10-16" },
  { id: "s-2", name: "مصنع دلتا كوتون", company: "تصنيع قطنيات", phone: "0100 664 2210", total: 96300, balance: 0, lastDeal: "2026-10-11" },
  { id: "s-3", name: "ليدر للأحذية والجلود", company: "أحذية وإكسسوارات", phone: "0112 447 9081", total: 74200, balance: 9500, lastDeal: "2026-10-08" },
  { id: "s-4", name: "تريد لاين للأزياء التركية", company: "استيراد", phone: "0227 330 118", total: 132900, balance: 27300, lastDeal: "2026-10-15" },
  { id: "s-5", name: "كيدز وورلد للتوريدات", company: "ملابس أطفال", phone: "0128 220 4471", total: 38900, balance: 0, lastDeal: "2026-09-29" },
];

function item(productIndex, color, size, qty, discountPct = 0) {
  const p = products[productIndex];
  const v = p.variants.find((x) => x.color === color && x.size === size) || p.variants[0];
  const gross = v.sellPrice * qty;
  const discount = +((gross * discountPct) / 100).toFixed(2);
  return {
    code: v.sku,
    barcode: v.barcode,
    name: p.name,
    color: v.color,
    size: v.size,
    qty,
    price: v.sellPrice,
    discountPct,
    discount,
    total: +(gross - discount).toFixed(2),
  };
}

function makeInvoice(index, config) {
  const items = config.items;
  const subTotal = +items.reduce((s, i) => s + i.price * i.qty, 0).toFixed(2);
  const discount = +items.reduce((s, i) => s + i.discount, 0).toFixed(2);
  const total = +(subTotal - discount).toFixed(2);
  const pieces = items.reduce((s, i) => s + i.qty, 0);
  return {
    id: `inv-${index + 1}`,
    number: `INV-2026-${String(60 + index + 1).padStart(4, "0")}`,
    date: config.date,
    customerId: config.customerId ?? null,
    customerName: config.customerName,
    customerPhone: config.customerPhone ?? "—",
    cashier: config.cashier,
    branch: shop.branch,
    payment: config.payment,
    status: config.status ?? "paid",
    paid: config.paid ?? total,
    items,
    subTotal,
    discount,
    total,
    pieces,
    returns: config.returns ?? [],
  };
}

export const invoices = [
  makeInvoice(0, {
    date: "2026-10-19T11:52:00",
    customerName: "عميل نقدي",
    cashier: "أحمد سمير",
    payment: "cash",
    items: [item(0, "أسود", "L", 2, 10), item(10, "بني", "مقاس واحد", 1, 0)],
  }),
  makeInvoice(1, {
    date: "2026-10-19T11:24:00",
    customerId: "c-1",
    customerName: "سارة إبراهيم",
    customerPhone: "0100 245 8871",
    cashier: "أحمد سمير",
    payment: "card",
    items: [item(4, "وردي", "M", 1, 5), item(5, "بيج", "M", 1, 0)],
  }),
  makeInvoice(2, {
    date: "2026-10-19T10:05:00",
    customerId: "c-3",
    customerName: "نورهان صالح",
    customerPhone: "0122 774 1180",
    cashier: "محمود فتحي",
    payment: "cash",
    items: [item(2, "كحلي", "32", 1, 0), item(7, "أخضر زيتي", "L", 2, 15)],
  }),
  makeInvoice(3, {
    date: "2026-10-19T09:41:00",
    customerName: "عميل نقدي",
    cashier: "أحمد سمير",
    payment: "wallet",
    status: "suspended",
    items: [item(8, "أسود", "42", 1, 0)],
  }),
  makeInvoice(4, {
    date: "2026-10-18T20:14:00",
    customerId: "c-2",
    customerName: "محمد عبد الرحمن",
    customerPhone: "0111 902 3345",
    cashier: "أحمد سمير",
    payment: "cash",
    status: "partial_return",
    items: [item(2, "أزرق فاتح", "L", 2, 5), item(12, "رمادي", "XL", 1, 0)],
    returns: [
      {
        id: "ret-1",
        date: "2026-10-19T09:12:00",
        type: "return",
        amount: 341,
        items: [{ name: products[2].name, color: "أزرق فاتح", size: "L", qty: 1 }],
        reason: "المقاس غير مناسب",
        handledBy: "منى عبد الله",
      },
    ],
  }),
  makeInvoice(5, {
    date: "2026-10-18T18:12:00",
    customerId: "c-2",
    customerName: "محمد عبد الرحمن",
    customerPhone: "0111 902 3345",
    cashier: "محمود فتحي",
    payment: "card",
    items: [item(6, "كحلي", "XL", 1, 0), item(0, "أبيض", "M", 2, 0)],
  }),
  makeInvoice(6, {
    date: "2026-10-18T16:35:00",
    customerName: "عميل نقدي",
    cashier: "أحمد سمير",
    payment: "cash",
    status: "returned",
    items: [item(5, "أحمر", "L", 1, 0)],
    returns: [
      {
        id: "ret-2",
        date: "2026-10-18T17:02:00",
        type: "return",
        amount: 450,
        items: [{ name: products[5].name, color: "أحمر", size: "L", qty: 1 }],
        reason: "عيب في المنتج",
        handledBy: "منى عبد الله",
      },
    ],
  }),
  makeInvoice(7, {
    date: "2026-10-17T20:30:00",
    customerId: "c-5",
    customerName: "أمنية رشاد",
    customerPhone: "0128 559 0034",
    cashier: "أحمد سمير",
    payment: "cash",
    items: [item(12, "كحلي", "M", 1, 10), item(10, "أسود", "مقاس واحد", 2, 0)],
  }),
  makeInvoice(8, {
    date: "2026-10-17T19:08:00",
    customerName: "عميل نقدي",
    cashier: "محمود فتحي",
    payment: "card",
    items: [item(3, "بيج", "L", 1, 0), item(7, "أسود", "XL", 1, 0)],
  }),
  makeInvoice(9, {
    date: "2026-10-17T13:22:00",
    customerId: "c-3",
    customerName: "نورهان صالح",
    customerPhone: "0122 774 1180",
    cashier: "أحمد سمير",
    payment: "wallet",
    items: [item(4, "كحلي", "M", 1, 0), item(6, "أزرق فاتح", "S", 1, 0), item(11, "وردي", "6 سنوات", 2, 0)],
  }),
  makeInvoice(10, {
    date: "2026-10-16T18:45:00",
    customerId: "c-1",
    customerName: "سارة إبراهيم",
    customerPhone: "0100 245 8871",
    cashier: "محمود فتحي",
    payment: "cash",
    items: [item(9, "بني", "41", 1, 5)],
  }),
  makeInvoice(11, {
    date: "2026-10-16T12:10:00",
    customerName: "عميل نقدي",
    cashier: "أحمد سمير",
    payment: "cash",
    items: [item(13, "كحلي", "L", 3, 20)],
  }),
  makeInvoice(12, {
    date: "2026-10-15T19:55:00",
    customerId: "c-4",
    customerName: "كريم الديب",
    customerPhone: "0106 331 7742",
    cashier: "أحمد سمير",
    payment: "card",
    items: [item(6, "كحلي", "L", 1, 0), item(0, "كحلي", "L", 1, 0)],
  }),
  makeInvoice(13, {
    date: "2026-10-15T13:40:00",
    customerId: "c-4",
    customerName: "كريم الديب",
    customerPhone: "0106 331 7742",
    cashier: "محمود فتحي",
    payment: "credit",
    items: [item(2, "كحلي", "M", 1, 0), item(1, "رمادي", "L", 1, 0)],
    paid: 500,
  }),
  makeInvoice(14, {
    date: "2026-10-14T17:30:00",
    customerName: "عميل نقدي",
    cashier: "أحمد سمير",
    payment: "cash",
    items: [item(11, "أزرق فاتح", "4 سنوات", 2, 0), item(0, "أسود", "S", 1, 0)],
  }),
  makeInvoice(15, {
    date: "2026-10-13T16:05:00",
    customerId: "c-5",
    customerName: "أمنية رشاد",
    customerPhone: "0128 559 0034",
    cashier: "منى عبد الله",
    payment: "cash",
    items: [item(5, "أسود", "L", 2, 10), item(10, "بني", "مقاس واحد", 1, 0)],
  }),
];

export const todayInvoices = invoices.filter((i) => i.date.startsWith("2026-10-19") && i.status !== "suspended");

export const dashboard = {
  todaySales: +todayInvoices.reduce((s, i) => s + i.total, 0).toFixed(2),
  todayReturns: 0,
  invoicesCount: todayInvoices.length,
  todayExpenses: 1450,
  lowStockCount: allVariants.filter((v) => stockStatus(v.stock, v.threshold) !== "in").length,
  netProfit: 6420.5,
};

export const salesSeries = {
  day: [
    { label: "الأحد 13", value: 8420 },
    { label: "الاثنين 14", value: 6180 },
    { label: "الثلاثاء 15", value: 11350 },
    { label: "الأربعاء 16", value: 9460 },
    { label: "الخميس 17", value: 14980 },
    { label: "الجمعة 18", value: 12240 },
    { label: "السبت 19", value: 9680 },
  ],
  week: [
    { label: "أسبوع 1", value: 52400 },
    { label: "أسبوع 2", value: 61150 },
    { label: "أسبوع 3", value: 47900 },
    { label: "أسبوع 4", value: 68320 },
    { label: "أسبوع 5", value: 72180 },
    { label: "الأسبوع الحالي", value: 72310 },
  ],
  month: [
    { label: "مايو", value: 214600 },
    { label: "يونيو", value: 198400 },
    { label: "يوليو", value: 245900 },
    { label: "أغسطس", value: 268300 },
    { label: "سبتمبر", value: 231750 },
    { label: "أكتوبر", value: 176420 },
  ],
};

export const topProducts = [
  { id: "p-3", name: "بنطلون جينز سليم فيت", category: "بناطيل", qty: 42, revenue: 28980 },
  { id: "p-1", name: "تيشيرت قطن بيما كتف عادي", category: "تيشيرتات", qty: 38, revenue: 13300 },
  { id: "p-5", name: "فستان كاجوال مشجر", category: "فساتين", qty: 17, revenue: 16660 },
  { id: "p-9", name: "حذاء رياضي خفيف", category: "أحذية", qty: 14, revenue: 13300 },
  { id: "p-8", name: "تيشيرت بولو بأزرار", category: "تيشيرتات", qty: 26, revenue: 10270 },
  { id: "p-7", name: "جاكيت جينز مبطن", category: "جواكت", qty: 8, revenue: 9200 },
];

export const lowStockAlerts = allVariants
  .filter((v) => stockStatus(v.stock, v.threshold) !== "in")
  .sort((a, b) => a.stock - b.stock)
  .slice(0, 8);

export const expenses = [
  { id: "ex-1", number: "EXP-1041", date: "2026-10-19T09:20:00", category: "مستلزمات تغليف", description: "أكياس وعلب تغليف", amount: 620, payment: "cash", employee: "منى عبد الله" },
  { id: "ex-2", number: "EXP-1040", date: "2026-10-19T08:05:00", category: "نقل وشحن", description: "توصيل طلبات الأمس", amount: 480, payment: "cash", employee: "محمود فتحي" },
  { id: "ex-3", number: "EXP-1039", date: "2026-10-19T07:50:00", category: "إنترنت واتصالات", description: "فاتورة الهاتف والإنترنت", amount: 350, payment: "card", employee: "منى عبد الله" },
  { id: "ex-4", number: "EXP-1038", date: "2026-10-18T18:30:00", category: "كهرباء ومياه", description: "فاتورة الكهرباء", amount: 2860, payment: "card", employee: "منى عبد الله" },
  { id: "ex-5", number: "EXP-1037", date: "2026-10-18T12:15:00", category: "تسويق وإعلانات", description: "إعلان ممول على السوشيال", amount: 1200, payment: "wallet", employee: "منى عبد الله" },
  { id: "ex-6", number: "EXP-1036", date: "2026-10-17T19:40:00", category: "صيانة", description: "صيانة ماكينة طباعة الملصقات", amount: 750, payment: "cash", employee: "أحمد سمير" },
  { id: "ex-7", number: "EXP-1035", date: "2026-10-17T10:00:00", category: "رواتب", description: "سلفة موظف", amount: 2000, payment: "cash", employee: "منى عبد الله" },
  { id: "ex-8", number: "EXP-1034", date: "2026-10-16T15:10:00", category: "نظافة", description: "مستلزمات نظافة المحل", amount: 310, payment: "cash", employee: "محمود فتحي" },
];

function ledger(productIndex, color, size, entries) {
  const v = allVariants.find((x) => x.productId === `p-${productIndex + 1}` && x.color === color && x.size === size);
  if (!v) return [];
  const netFlow = entries.reduce((s, e) => s + (e.qtyIn || 0) - (e.qtyOut || 0), 0);
  const opening = v.stock - netFlow;
  const rows = [
    {
      id: `${v.sku}-open`,
      date: "2026-10-01T09:00:00",
      productName: v.productName,
      variant: `${v.color} / ${v.size}`,
      sku: v.sku,
      type: "purchase",
      qtyIn: opening > 0 ? opening : 0,
      qtyOut: 0,
      doc: "PO-2026-0118",
      employee: "منى عبد الله",
    },
    ...entries.map((e, i) => ({
      id: `${v.sku}-${i}`,
      date: e.date,
      productName: v.productName,
      variant: `${v.color} / ${v.size}`,
      sku: v.sku,
      type: e.type,
      qtyIn: e.qtyIn || 0,
      qtyOut: e.qtyOut || 0,
      doc: e.doc,
      employee: e.employee,
    })),
  ];
  let balance = 0;
  return rows.map((r) => {
    balance += (r.qtyIn || 0) - (r.qtyOut || 0);
    return { ...r, balance };
  });
}

export const stockMovements = [
  ...ledger(2, "كحلي", "L", [
    { date: "2026-10-03T11:20:00", type: "sale", qtyOut: 2, doc: "INV-2026-0064", employee: "أحمد سمير" },
    { date: "2026-10-08T17:05:00", type: "return", qtyIn: 1, doc: "RET-2026-0012", employee: "منى عبد الله" },
    { date: "2026-10-11T14:30:00", type: "transfer", qtyOut: 3, doc: "TR-2026-0007", employee: "منى عبد الله" },
    { date: "2026-10-12T10:15:00", type: "sale", qtyOut: 4, doc: "INV-2026-0071", employee: "محمود فتحي" },
    { date: "2026-10-16T18:45:00", type: "exchange", qtyOut: 1, doc: "EXC-2026-0004", employee: "أحمد سمير" },
    { date: "2026-10-19T10:05:00", type: "sale", qtyOut: 1, doc: "INV-2026-0062", employee: "محمود فتحي" },
  ]),
  ...ledger(0, "أسود", "L", [
    { date: "2026-10-05T13:10:00", type: "sale", qtyOut: 3, doc: "INV-2026-0066", employee: "أحمد سمير" },
    { date: "2026-10-09T16:40:00", type: "adjustment", qtyOut: 1, doc: "STK-2026-0002", employee: "منى عبد الله" },
    { date: "2026-10-15T12:25:00", type: "sale", qtyOut: 2, doc: "INV-2026-0075", employee: "أحمد سمير" },
    { date: "2026-10-19T11:52:00", type: "sale", qtyOut: 2, doc: "INV-2026-0060", employee: "أحمد سمير" },
  ]),
  ...ledger(4, "وردي", "M", [
    { date: "2026-10-06T18:00:00", type: "sale", qtyOut: 1, doc: "INV-2026-0068", employee: "محمود فتحي" },
    { date: "2026-10-19T11:24:00", type: "sale", qtyOut: 1, doc: "INV-2026-0061", employee: "أحمد سمير" },
  ]),
  ...ledger(8, "أسود", "42", [
    { date: "2026-10-04T15:35:00", type: "purchase", qtyIn: 6, doc: "PO-2026-0121", employee: "منى عبد الله" },
    { date: "2026-10-10T19:10:00", type: "sale", qtyOut: 2, doc: "INV-2026-0070", employee: "أحمد سمير" },
    { date: "2026-10-17T13:50:00", type: "sale", qtyOut: 1, doc: "INV-2026-0081", employee: "محمود فتحي" },
  ]),
  ...ledger(11, "وردي", "4 سنوات", [
    { date: "2026-10-02T12:40:00", type: "purchase", qtyIn: 4, doc: "PO-2026-0119", employee: "منى عبد الله" },
    { date: "2026-10-14T17:30:00", type: "sale", qtyOut: 2, doc: "INV-2026-0074", employee: "أحمد سمير" },
    { date: "2026-10-17T13:22:00", type: "sale", qtyOut: 2, doc: "INV-2026-0069", employee: "أحمد سمير" },
  ]),
  ...ledger(5, "أحمر", "M", [
    { date: "2026-10-07T11:05:00", type: "sale", qtyOut: 2, doc: "INV-2026-0067", employee: "أحمد سمير" },
    { date: "2026-10-13T16:05:00", type: "adjustment", qtyOut: 1, doc: "STK-2026-0003", employee: "منى عبد الله" },
  ]),
].sort((a, b) => new Date(b.date) - new Date(a.date));

export const stocktakeRows = allVariants
  .filter((v) => ["p-1", "p-2", "p-3"].includes(v.productId))
  .slice(0, 12)
  .map((v, i) => ({ ...v, actual: Math.max(0, v.stock - (i % 3 === 0 ? 1 : 0)), counted: i % 4 !== 0 }));

export const notifications = [
  { id: "n-1", title: "نواقص مخزون", body: `${dashboard.lowStockCount} متغيراً وصل إلى حد إعادة الطلب`, tone: "warning", time: "قبل ١٢ دقيقة" },
  { id: "n-2", title: "فاتورة معلقة", body: "INV-2026-0063 معلقة بانتظار العميل", tone: "info", time: "قبل ٢٣ دقيقة" },
  { id: "n-3", title: "توريد جديد", body: "وصلت شحنة ١٢ صنفاً من شركة النيل", tone: "success", time: "قبل ساعة" },
];

export const reports = {
  profit: { revenue: 176420, cogs: 98640, gross: 77780, discounts: 8940, returns: 3210, expenses: 18760 },
};

export const initialSuspended = [
  {
    id: "hold-1",
    number: "INV-2026-0063",
    customerName: "عميل نقدي",
    customerPhone: "—",
    cashier: "أحمد سمير",
    heldAt: "2026-10-19T09:41:00",
    note: "بانتظار العميل لإحضار الكوبون",
    items: [{ ...item(8, "أسود", "42", 1, 0), variantId: "v-hold-1" }],
  },
];

export function invoiceById(id) {
  return invoices.find((i) => i.id === id || i.number === id) ?? null;
}