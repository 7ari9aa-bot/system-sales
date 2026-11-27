/**
 * حدود المنتج في مكان واحد، مش أرقام متفرقة في الشاشة والباك إند.
 *
 * الباك إند بيرفض أي طلب فيه أكثر من MAX_VARIANTS_PER_PRODUCT تركيبة
 * (ProductIntakeRequest.variants max_length)، فالشاشة لازم توقف قبل الطلب
 * بدل ما التاجر يبني 12,000 صف ثم يشوف خطأ من السيرفر.
 */
export const MAX_VARIANTS_PER_PRODUCT = 500;
export const MAX_COLORS_PER_PRODUCT = 200;
export const MAX_SIZES_PER_PRODUCT = 60;

/** عدد التركيبات الناتج عن لون × مقاس، قبل أي توليد. */
export const variantCount = (colors = [], sizes = []) => colors.length * sizes.length;

/**
 * هل المصفوفة دي مسموح بتوليدها؟ رسالة عربية واحدة تشرح الرقم والحد،
 * أو null لما تكون سليمة.
 */
export function variantLimitProblem(colors = [], sizes = []) {
  const count = variantCount(colors, sizes);
  if (count === 0) return "اختر لون واحد ومقاس واحد على الأقل";
  if (count > MAX_VARIANTS_PER_PRODUCT) {
    return `هذه المصفوفة تُنتج ${count} تركيبة، والحد ${MAX_VARIANTS_PER_PRODUCT} تركيبة للمنتج الواحد — قلّل الألوان أو المقاسات`;
  }
  return null;
}
