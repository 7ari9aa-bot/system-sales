import { useRef } from "react";
import { saveButtonState } from "@/applications/apparel/lib/saveOnce";
import { ChevronLeft, ChevronRight, Download, ImageOff, Plus, Trash2, X } from "lucide-react";
import { MAX_IMAGES_PER_SKU } from "@/applications/apparel/lib/productImageRules";
import {
  CARD,
  CARD_PAD,
  CTA_ICON,
  CTA_PRIMARY,
  CTA_ROW,
  DROP_ZONE,
  PIC,
  SIDE,
  THUMB,
  THUMBS,
} from "@/applications/apparel/components/products/formStyles";

// عمود صور المنتج: الصورة الرئيسية، الصور المحفوظة في النظام، الصور الجديدة قبل الرفع، وأزرار الحفظ والإلغاء.
// لا توجد صورة افتراضية مزيفة: لو المنتج بلا صور نعرض حالة فارغة صريحة.
export default function ProductImageCard({
  saved = [],
  picked = [],
  maxImages = MAX_IMAGES_PER_SKU,
  onPickImages,
  onRemovePicked,
  // صور محفوظة: حذف، ترتيب، وربط بلون — كلها بتحفظ على السيرفر من غير إعادة رفع.
  colors = [],
  onDeleteSaved,
  onMoveSaved,
  onBindSaved,
  // تقدم الرفع لكل صورة: { [index]: { status, message } }
  progress = {},
  failedCount = 0,
  onRetryFailed,
  canSave,
  isSaving = false,
  onSave,
  onCancel,
}) {
  const inputRef = useRef(null);
  const total = saved.length + picked.length;
  const full = total >= maxImages;
  const openPicker = () => !full && inputRef.current?.click();
  const main = saved[0]?.url ?? picked[0]?.url ?? null;
  const state = saveButtonState({ canSave, isSaving });

  return (
    <div className={`${CARD} ${CARD_PAD} ${SIDE}`}>
      <div className={PIC}>
        {main ? (
          <img src={main} alt="صورة المنتج" className="block h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-[13px] text-[#7A766C]">
            <ImageOff className="h-8 w-8" />
            لا توجد صورة للمنتج
          </div>
        )}
      </div>

      <div className={THUMBS}>
        {saved.slice(0, maxImages).map((img, index) => (
          <div key={img.id} className="group relative aspect-square overflow-hidden rounded-xl border border-[#e6e1da]">
            <img src={img.url} alt="صورة محفوظة" className="h-full w-full object-cover" />
            {onDeleteSaved && (
              <button
                type="button"
                onClick={() => onDeleteSaved(img)}
                aria-label={`حذف الصورة ${index + 1}`}
                className="absolute end-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-white/90 text-[#b3261e] shadow"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
            {onMoveSaved && index > 0 && (
              <button
                type="button"
                onClick={() => onMoveSaved(img, -1)}
                aria-label={`تحريك الصورة ${index + 1} لليمين`}
                className="absolute bottom-1 end-1 flex h-6 w-6 items-center justify-center rounded-full bg-white/90 text-[#3a362f] shadow"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            )}
            {onMoveSaved && index < saved.length - 1 && (
              <button
                type="button"
                onClick={() => onMoveSaved(img, 1)}
                aria-label={`تحريك الصورة ${index + 1} لليسار`}
                className="absolute bottom-1 start-1 flex h-6 w-6 items-center justify-center rounded-full bg-white/90 text-[#3a362f] shadow"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
            )}
            {onBindSaved && colors.length > 0 && (
              <select
                value={img.variantId ?? ""}
                onChange={(e) => onBindSaved(img, e.target.value || null)}
                aria-label={`ربط الصورة ${index + 1} بلون`}
                className="absolute inset-x-1 top-8 rounded-md border border-[#e6e1da] bg-white/95 px-1 py-0.5 text-[10px]"
              >
                <option value="">معرض المنتج</option>
                {colors.map((c) => (
                  <option key={c.variantId} value={c.variantId}>{c.name}</option>
                ))}
              </select>
            )}
          </div>
        ))}
        {picked.map((img, i) => (
          <div key={img.url} className="relative aspect-square overflow-hidden rounded-xl border-2 border-[#f5a766]">
            <img src={img.url} alt="صورة جديدة" className="h-full w-full object-cover" />
            {progress[i]?.status && progress[i].status !== "idle" && (
              <span className="absolute inset-x-0 bottom-0 bg-black/70 py-0.5 text-center text-[10px] text-white">
                {progress[i].status === "uploading" ? "جاري الرفع…" : progress[i].status === "done" ? "تم الرفع" : "فشل الرفع"}
              </span>
            )}
            <button
              type="button"
              onClick={() => onRemovePicked?.(i)}
              aria-label="إزالة الصورة"
              className="absolute end-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-white/90 text-[#3a362f] shadow"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        {!full && (
          <button type="button" className={THUMB} onClick={openPicker} aria-label="إضافة صورة">
            <Plus className="h-[22px] w-[22px]" />
          </button>
        )}
      </div>

      <button
        type="button"
        className={DROP_ZONE}
        disabled={full}
        onClick={openPicker}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (!full) onPickImages?.(e.dataTransfer?.files);
        }}
      >
        <Download className="h-6 w-6" />
        {full ? `وصلت للحد الأقصى (${maxImages} صور)` : "اسحب الصور هنا أو اضغط للاختيار"}
      </button>

      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/gif,image/webp,image/bmp"
        multiple
        className="hidden"
        onChange={(e) => {
          onPickImages?.(e.target.files);
          e.target.value = "";
        }}
      />

      {failedCount > 0 && (
        <button type="button" onClick={onRetryFailed} className="text-[12px] font-semibold text-[#b3261e] underline">
          إعادة محاولة {failedCount} صورة فشلت
        </button>
      )}

      <div className={CTA_ROW}>
        <button
          type="button"
          className={CTA_PRIMARY}
          disabled={state.disabled}
          aria-busy={isSaving}
          onClick={onSave}
        >
          {state.label}
        </button>
        <button type="button" className={CTA_ICON} onClick={onCancel} aria-label="إلغاء التعديلات">
          <X className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}
