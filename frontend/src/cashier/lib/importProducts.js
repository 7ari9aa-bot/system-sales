// تحويل صفوف ملف Excel/CSV المستخرجة إلى منتجات بتركيبات اللون والمقاس والباركود.

import { brands, categories, shop } from "@/cashier/lib/mockData";

function num(value, fallback = 0) {
  const n = Number(String(value ?? "").replace(/[^\d.-]/g, ""));
  return Number.isFinite(n) ? n : fallback;
}

let barcodeCounter = 0;
const nextBarcode = () => String(2990000000000 + (barcodeCounter += 1));

// كل صف = تركيبة (لون + مقاس)، والصفوف التي تحمل نفس اسم المنتج تُدمج في منتج واحد.
export function buildProductsFromRows(rows) {
  const groups = new Map();

  rows.forEach((row) => {
    const name = String(row?.name ?? "").trim();
    if (!name) return;
    const group = groups.get(name) ?? { name, category: "", brand: "", lines: [] };
    if (!group.category) group.category = String(row.category ?? "").trim();
    if (!group.brand) group.brand = String(row.brand ?? "").trim();
    group.lines.push({
      color: String(row.color ?? "").trim() || "أساسي",
      size: String(row.size ?? "").trim() || "مقاس واحد",
      sku: String(row.sku ?? "").trim(),
      barcode: String(row.barcode ?? "").trim(),
      buyPrice: num(row.buyPrice),
      sellPrice: num(row.sellPrice),
      stock: Math.max(0, Math.round(num(row.stock))),
    });
    groups.set(name, group);
  });

  return [...groups.values()].map((group, gi) => {
    const id = `imp-${Date.now()}-${gi}`;
    const buyPrice = group.lines.find((l) => l.buyPrice)?.buyPrice ?? 0;
    const sellPrice = group.lines.find((l) => l.sellPrice)?.sellPrice ?? 0;

    const variants = group.lines.map((line, li) => ({
      id: `${id}-${li + 1}`,
      productId: id,
      productName: group.name,
      color: line.color,
      size: line.size,
      sku: line.sku || `${id.toUpperCase()}-${String(li + 1).padStart(2, "0")}`,
      barcode: line.barcode || nextBarcode(),
      stock: line.stock,
      buyPrice: line.buyPrice || buyPrice,
      sellPrice: line.sellPrice || sellPrice,
    }));

    return {
      id,
      sku: group.lines[0]?.sku || `${id.toUpperCase()}-00`,
      barcode: variants[0].barcode,
      name: group.name,
      category: group.category || categories[0],
      brand: group.brand || brands[0],
      description: `${group.name} — مُستورد من ملف Excel.`,
      buyPrice,
      sellPrice,
      threshold: shop.lowStockThreshold,
      status: "active",
      variants,
      variantsCount: variants.length,
      totalStock: variants.reduce((s, v) => s + v.stock, 0),
      colors: [...new Set(variants.map((v) => v.color))],
      sizes: [...new Set(variants.map((v) => v.size))],
    };
  });
}