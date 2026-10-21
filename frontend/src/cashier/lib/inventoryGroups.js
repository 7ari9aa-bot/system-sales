// تجميع متغيرات المخزون المعروضة في بطاقات منتجات (الرصيد الإجمالي، عدد التركيبات، حالة التوفر).
// حالة كل متغير يقررها الخادم وحده؛ هنا لا تُعاد حسابها. حالة المنتج هي الأسوأ بين متغيراته:
// الجمع كان يُخفي أن مقاسًا بعينه نفد طالما بقية المقاسات متوفرة.

const SEVERITY = { in: 0, low: 1, out: 2 };

export function worstStatus(statuses) {
  return statuses.reduce((worst, s) => ((SEVERITY[s] ?? 0) > (SEVERITY[worst] ?? 0) ? s : worst), "in");
}

export function groupVariantsByProduct(rows) {
  const groups = new Map();

  rows.forEach((v) => {
    const group =
      groups.get(v.productId) ??
      {
        id: v.productId,
        name: v.productName,
        sku: v.sku,
        category: v.category,
        brand: v.brand ?? "",
        price: v.sellPrice,
        stock: 0,
        variants: [],
      };
    group.stock += v.stock;
    group.variants.push(v);
    groups.set(v.productId, group);
  });

  return [...groups.values()].map((g) => ({
    ...g,
    variantsCount: g.variants.length,
    statusValue: worstStatus(g.variants.map((v) => v.status)),
  }));
}

/**
 * The product to show in the details dialog. A grid card is opened BY ID and re-derived from the live
 * rows on every render, so a change saved in the dialog (a new reorder level, hence a new status)
 * shows up at once. Keeping a copy taken at click time would keep showing the old status.
 * A product that comes whole (the mock "system products" section) is shown as it is.
 */
export function resolveOpenProduct(open, rows) {
  if (!open) return null;
  if (typeof open !== "string") return open;
  return groupVariantsByProduct(rows).find((g) => g.id === open) ?? null;
}
