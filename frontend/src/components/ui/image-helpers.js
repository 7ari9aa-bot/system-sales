/** بدائل مبسطة لمساعدات صور Base44 — بدون أي CDN تحويلات:
 *  الصور بتتمرر زي ما هي. كافية لكل استخدامات Image/ResponsiveImage
 *  في التطبيق لأن مفيش تحويلات CDN حقيقية بعد شيل Base44. */

export const DEFAULT_TRANSFORM_WIDTH = 1024;

export function getImagePreviewClassName(className = "", wrapperClassName = "", extra = "") {
  return [wrapperClassName, className, extra].filter(Boolean).join(" ");
}

/** مفيش srcset من غير CDN — بنرجع undefined عشان المتصفح يستخدم src. */
export function buildSrcSet() {
  return undefined;
}

export function buildTransformUrl(src) {
  return src;
}

/** فصل خصائص الصورة عن خصائص الغلاف — نفس العقد القديم. */
export function splitImageProps(props = {}) {
  const { width, height, fit, focalPoint, quality, className, ...rest } = props;
  return {
    imgProps: rest,
    wrapperProps: { className },
    meta: { width, height, fit, focalPoint, quality },
  };
}
