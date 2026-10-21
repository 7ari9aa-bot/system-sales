import { useRef } from "react";
import { Download, ImageOff, Plus, X } from "lucide-react";
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
} from "@/cashier/components/products/formStyles";

// عمود صور المنتج: الصورة الرئيسية، الصور المحفوظة في النظام، الصور الجديدة قبل الرفع، وأزرار الحفظ والإلغاء.
// لا توجد صورة افتراضية مزيفة: لو المنتج بلا صور نعرض حالة فارغة صريحة.
export default function ProductImageCard({
  saved = [],
  picked = [],
  maxImages = 4,
  onPickImages,
  onRemovePicked,
  canSave,
  onSave,
  onCancel,
}) {
  const inputRef = useRef(null);
  const total = saved.length + picked.length;
  const full = total >= maxImages;
  const openPicker = () => !full && inputRef.current?.click();
  const main = saved[0]?.url ?? picked[0]?.url ?? null;

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
        {saved.slice(0, maxImages).map((img) => (
          <div key={img.id} className="aspect-square overflow-hidden rounded-xl border border-[#e6e1da]">
            <img src={img.url} alt="صورة محفوظة" className="h-full w-full object-cover" />
          </div>
        ))}
        {picked.map((img, i) => (
          <div key={img.url} className="relative aspect-square overflow-hidden rounded-xl border-2 border-[#f5a766]">
            <img src={img.url} alt="صورة جديدة" className="h-full w-full object-cover" />
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

      <div className={CTA_ROW}>
        <button type="button" className={CTA_PRIMARY} disabled={!canSave} onClick={onSave}>
          حفظ المنتج
        </button>
        <button type="button" className={CTA_ICON} onClick={onCancel} aria-label="إلغاء التعديلات">
          <X className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}
