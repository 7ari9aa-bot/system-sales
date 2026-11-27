/**
 * تقرير رفع الصور بالـSKU: اللي اتربط، واللي مالوش صنف، واللي مش صورة، واللي فوق الحد.
 * الدالة نقيّة عشان الرسائل تتختبر من غير شبكة ولا متصفح.
 */

export { MAX_IMAGE_BYTES_MB, MAX_IMAGES_PER_SKU } from "@/cashier/lib/productImageRules";
import { MAX_IMAGES_PER_SKU } from "@/cashier/lib/productImageRules";

export function zipFileProblem(file) {
  if (!file) return "اختر ملفًا مضغوطًا أولًا";
  if (!String(file.name ?? "").toLowerCase().endsWith(".zip")) return "لازم ملف .zip فيه الصور";
  if (!(file.size > 0)) return "الملف فاضي";
  if (file.size > 60 * 1024 * 1024) return "حجم الملف المضغوط أكبر من 60 ميجابايت";
  return null;
}

/** سطور التقرير بالعربي. القائمة الفاضية معناها إن الحاجة دي ماحصلتش. */
export function reportLines(report) {
  if (!report) return [];
  const stats = report.stats ?? {};
  const lines = [];

  if (stats.attached) {
    const skus = new Set((report.matched ?? []).map((m) => m.sku));
    lines.push(`اتربطت ${stats.attached} صورة على ${skus.size} صنف`);
  }
  if (report.unknown_skus?.length) {
    lines.push(`أصناف مش موجودة في المتجر: ${report.unknown_skus.join("، ")}`);
  }
  if (report.not_pictures?.length) {
    lines.push(`ملفات مش صور: ${report.not_pictures.slice(0, 5).join("، ")}${report.not_pictures.length > 5 ? "…" : ""}`);
  }
  if (report.over_limit?.length) {
    lines.push(`فوق حد ${MAX_IMAGES_PER_SKU} صور للصنف: ${report.over_limit.length} صورة ماترفعتش`);
  }
  if (report.failed?.length) {
    lines.push(...report.failed.slice(0, 5).map((f) => `${f.file}: ${f.reason}`));
  }
  if (!lines.length) lines.push("لم تُرفع صور: راجع أسماء الملفات (اسم الملف = SKU)");
  return lines;
}

/** زر/رسالة واحدة: هل الرفع نجح كله، جزئي، ولا فشل؟ */
export function reportTone(report) {
  if (!report) return "idle";
  const stats = report.stats ?? {};
  if (!stats.attached) return "bad";
  const problems =
    (stats.unknown ?? 0) + (stats.not_pictures ?? 0) + (stats.over_limit ?? 0) + (stats.failed ?? 0);
  return problems ? "partial" : "good";
}
