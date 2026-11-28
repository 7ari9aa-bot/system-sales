/**
 * سطر صفحة المنتجات: صف واحد لكل منتج في الكتالوج (مش لكل رصيد في المخزن).
 *
 * شاشة المخزون بتعرض التركيبات وأرصدتها؛ دي بتعرض الموديل نفسه: اسمه، تصنيفه، ماركته،
 * موسمه، خامته، عدد تركيباته، ونطاق سعره. الفلترة هنا على الكتالوج فقط، فمنتج مالوش رصيد
 * في أي مخزن لسه بيظهر — لأنه موجود فعلًا ويحتاج تعديل أو أرشفة.
 */

const money = (value) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

export const PRODUCT_STATUS = {
  active: { label: "متاح للبيع", tone: "bg-[#eaf7ee] text-[#1e7a3c] border-[#bfe6cb]" },
  draft: { label: "مسودة", tone: "bg-[#fdf3e4] text-[#96631a] border-[#f2ddb6]" },
  archived: { label: "مؤرشف", tone: "bg-[#f1efec] text-[#6b6358] border-[#ddd7cf]" },
};

export function toProductRow(product = {}) {
  const variants = Array.isArray(product.variants) ? product.variants : [];
  const prices = variants.map((v) => money(v.price)).filter((n) => n !== null);
  const active = variants.filter((v) => v.is_active !== false);
  const image = Array.isArray(product.images) ? product.images[0] : null;
  return {
    id: String(product.id ?? ""),
    title: String(product.title ?? "").trim(),
    slug: String(product.slug ?? ""),
    status: String(product.status ?? "active"),
    season: String(product.season ?? "").trim(),
    material: String(product.material ?? "").trim(),
    categoryId: product.category_id ? String(product.category_id) : "",
    brandId: product.brand_id ? String(product.brand_id) : "",
    variantCount: variants.length,
    activeVariantCount: active.length,
    skus: variants.map((v) => String(v.sku ?? "")).filter(Boolean),
    priceFrom: prices.length ? Math.min(...prices) : null,
    priceTo: prices.length ? Math.max(...prices) : null,
    imageUrl: image?.url ?? image?.thumb_url ?? null,
  };
}

/** النص اللي التاجر بيدوّر بيه: الاسم، المعرّف، أو أي SKU جوه المنتج. */
function matchesTerm(row, term) {
  if (!term) return true;
  const needle = term.trim().toLowerCase();
  if (!needle) return true;
  if (row.title.toLowerCase().includes(needle)) return true;
  if (row.slug.toLowerCase().includes(needle)) return true;
  return row.skus.some((sku) => sku.toLowerCase().includes(needle));
}

/**
 * status: "" يعني الكل. "active" بيفصل المؤرشف والمسودة، عشان الشاشة الافتراضية
 * تعرض اللي بيتباع فعلًا من غير ما تخفي الباقي عن اللي بيدوّر عليه.
 */
export function filterProductRows(rows = [], filters = {}) {
  const { term = "", categoryId = "", brandId = "", season = "", material = "", status = "" } =
    filters;
  return rows.filter(
    (row) =>
      matchesTerm(row, term) &&
      (!categoryId || row.categoryId === categoryId) &&
      (!brandId || row.brandId === brandId) &&
      (!season || row.season === season) &&
      (!material || row.material === material) &&
      (!status || row.status === status),
  );
}

export function sortProductRows(rows = []) {
  return [...rows].sort((a, b) => a.title.localeCompare(b.title, "ar"));
}

/** "١٢٠ – ٢٥٠ ج.م"، أو رقم واحد لو كل التركيبات بنفس السعر، أو شرطة لو مفيش سعر. */
export function priceRangeLabel(row, format = (n) => String(n)) {
  if (row.priceFrom === null) return "—";
  if (row.priceFrom === row.priceTo) return `${format(row.priceFrom)} ج.م`;
  return `${format(row.priceFrom)} – ${format(row.priceTo)} ج.م`;
}

/** عدّاد الحالات للشرايط فوق الجدول. */
export function statusCounts(rows = []) {
  return rows.reduce(
    (acc, row) => ({ ...acc, [row.status]: (acc[row.status] ?? 0) + 1 }),
    { active: 0, draft: 0, archived: 0 },
  );
}
