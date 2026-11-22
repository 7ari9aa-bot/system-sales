/**
 * بيانات المحل اللي بتتكرر في كل منتج (الموسم، الماركة، الفئة، الخامة، حد التنبيه).
 * بعد حفظ منتج بنسيبها في النموذج عشان صاحب المحل يدخل الموديل اللي بعده من غير ما يختارها من الأول.
 * اللي بيخص المنتج نفسه (الاسم، الوصف، السعر، الألوان، المقاسات، التركيبات، الصور) بيتفضّى.
 */
export const PRODUCT_SEED_FIELDS = ["categoryId", "brandId", "season", "material", "threshold"];

export function nextProductSeed(values = {}) {
  const seed = {};
  for (const field of PRODUCT_SEED_FIELDS) {
    const value = values?.[field];
    seed[field] = value ?? "";
  }
  return seed;
}

/** حالة النموذج الابتدائية: في التعديل المنتج هو المصدر، وفي الإضافة بادئة الموسم/الفئة/الماركة/الخامة. */
export function initialProductForm(product, seed) {
  return {
    name: product?.name ?? "",
    categoryId: product?.categoryId ?? seed?.categoryId ?? "",
    brandId: product?.brandId ?? seed?.brandId ?? "",
    season: product?.season ?? seed?.season ?? "",
    material: product?.material ?? seed?.material ?? "",
    description: product?.description ?? "",
    sellPrice: product?.sellPrice ?? "",
    threshold: product?.threshold ?? seed?.threshold ?? "",
  };
}
