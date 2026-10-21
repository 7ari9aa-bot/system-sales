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
 * Upload several files one after another (the backend appends each, so order = pick order).
 * Never throws: returns { uploaded, failed:[{name, message}] } so a product that was saved is not
 * reported as failed just because one photo did not go through.
 */
export async function uploadProductImages(productId, files) {
  const uploaded = [];
  const failed = [];
  for (const file of files ?? []) {
    try {
      uploaded.push(await uploadProductImage(productId, file));
    } catch (e) {
      failed.push({ name: file?.name ?? "صورة", message: e?.message ?? "تعذّر رفع الصورة" });
    }
  }
  return { uploaded, failed };
}
