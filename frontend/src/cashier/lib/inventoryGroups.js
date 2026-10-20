// تجميع متغيرات المخزون المعروضة في بطاقات منتجات (الرصيد الإجمالي، عدد التركيبات، حالة التوفر).
import { products, stockStatus } from "@/cashier/lib/mockData";

const PRODUCTS_BY_ID = new Map(products.map((p) => [p.id, p]));

export function groupVariantsByProduct(rows) {
  const groups = new Map();

  rows.forEach((v) => {
    const product = PRODUCTS_BY_ID.get(v.productId);
    const group =
      groups.get(v.productId) ??
      {
        id: v.productId,
        name: v.productName,
        sku: product?.sku ?? v.sku,
        category: v.category,
        brand: v.brand,
        price: v.sellPrice,
        threshold: v.threshold,
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
    statusValue: stockStatus(g.stock, g.threshold),
  }));
}