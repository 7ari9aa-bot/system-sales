/**
 * Product photo upload. The backend (POST /products/{id}/images/upload) takes the raw file as the
 * request body and re-checks the type, the file signature and the 10 MB cap. We check the same things
 * here first so the owner gets a clear message before any upload starts, not a 422 afterwards.
 */
import { api } from "@/lib/api";

export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"];

const seg = (v) => encodeURIComponent(String(v));

/** null when the file can be uploaded, otherwise the reason (Arabic, shown to the owner). */
export function imageProblem(file) {
  if (!file) return "اختر صورة أولًا";
  if (!IMAGE_TYPES.includes(String(file.type).toLowerCase())) return "نوع الصورة غير مدعوم. استخدم JPEG أو PNG أو WebP أو GIF أو BMP.";
  if (!(file.size > 0)) return "الملف فارغ";
  if (file.size > MAX_IMAGE_BYTES) return "حجم الصورة أكبر من 10 ميجابايت";
  return null;
}

/** The product's photos as the form shows them: [{ id, url }], in the stored order. */
export function imagesOf(product) {
  return [...(product?.images ?? [])]
    .filter((i) => i?.url)
    .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    .map((i) => ({ id: i.id, url: i.url }));
}

/** Upload one file to a product. Throws a plain Error with a readable message on any failure. */
export async function uploadProductImage(productId, file) {
  const problem = imageProblem(file);
  if (problem) throw new Error(problem);
  try {
    return await api(`/products/${seg(productId)}/images/upload`, {
      method: "POST",
      body: file,
      rawBody: true,
      contentType: file.type,
    });
  } catch (e) {
    if (e?.status === 503 || e?.code === "storage_unavailable") throw new Error("تخزين الصور غير متاح الآن. حاول لاحقًا.");
    throw e;
  }
}

/**
 * رفع مجموعة صور: 3 في نفس الوقت بدل صورة وراء صورة.
 * ما بيرميش: بيرجّع { uploaded, failed } — المنتج اتحفظ خلاص، فصورة فشلت مش سبب لتقرير فشل الحفظ.
 * onProgress(index, { status, message }) بيتنادى لكل صورة عشان الشاشة تعرض تقدمها.
 */
export async function uploadProductImages(productId, files, { concurrency = 3, onProgress } = {}) {
  const list = [...(files ?? [])];
  const uploaded = [];
  const failed = [];
  let next = 0;

  const report = (index, status, message) => {
    try {
      onProgress?.(index, { status, message });
    } catch {
      // تقدم الصورة مش سبب لتوقف الرفع
    }
  };

  const worker = async () => {
    while (next < list.length) {
      const index = next;
      next += 1;
      const file = list[index];
      report(index, "uploading");
      try {
        uploaded.push(await uploadProductImage(productId, file));
        report(index, "done");
      } catch (e) {
        const message = e?.message ?? "تعذّر رفع الصورة";
        failed.push({ index, name: file?.name ?? "صورة", message, file });
        report(index, "failed", message);
      }
    }
  };

  const workers = Array.from({ length: Math.max(1, Math.min(concurrency, list.length)) }, worker);
  await Promise.all(workers);
  return { uploaded, failed };
}

/** إعادة محاولة الصور اللي فشلت بس، من غير ما نرفع اللي نجح تاني. */
export async function retryFailedImages(productId, failed = [], options = {}) {
  const files = failed.map((f) => f.file).filter(Boolean);
  if (files.length === 0) return { uploaded: [], failed };
  return uploadProductImages(productId, files, options);
}

/** حذف صورة محفوظة (الصف والملف المخزّن). */
export async function deleteProductImage(productId, imageId) {
  return api(`/products/${seg(productId)}/images/${seg(imageId)}`, { method: "DELETE" });
}

/** ترتيب المعرض: كل الصور بالترتيب المطلوب. */
export async function reorderProductImages(productId, imageIds) {
  return api(`/products/${seg(productId)}/images/order`, { method: "POST", body: { image_ids: imageIds } });
}

/** ربط صورة بلون/تركيبة معيّنة، أو رجوعها لمعرض المنتج بـ variantId = null. */
export async function bindProductImage(productId, imageId, variantId) {
  return api(`/products/${seg(productId)}/images/${seg(imageId)}`, {
    method: "PATCH",
    body: variantId ? { variant_id: variantId } : { unbind_variant: true },
  });
}
