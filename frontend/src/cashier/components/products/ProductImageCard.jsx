import { useRef } from "react";
import { Download, Plus, X } from "lucide-react";
import { Image } from "@/cashier/components/ui/image";
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

const PLACEHOLDER = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/0031f8601_generated_81c289a8.jpg";

// عمود صورة الموديل: المعاينة، خانات الصور، منطقة الإفلات، وأزرار الحفظ والإلغاء.
export default function ProductImageCard({ preview, onPickImage, canSave, onSave, onCancel }) {
  const inputRef = useRef(null);
  const openPicker = () => inputRef.current?.click();

  return (
    <div className={`${CARD} ${CARD_PAD} ${SIDE}`}>
      <div className={PIC}>
        <Image src={preview || PLACEHOLDER} alt="صورة الموديل" fittingType="fill" className="block h-full w-full object-cover" />
      </div>

      <div className={THUMBS}>
        {[0, 1, 2].map((slot) => (
          <button key={slot} type="button" className={THUMB} onClick={openPicker} aria-label="إضافة صورة">
            <Plus className="h-[22px] w-[22px]" />
          </button>
        ))}
      </div>

      <button
        type="button"
        className={DROP_ZONE}
        onClick={openPicker}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          onPickImage?.(e.dataTransfer?.files?.[0]);
        }}
      >
        <Download className="h-6 w-6" />
        اسحب صورة هنا أو اضغط للاختيار
      </button>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => onPickImage?.(e.target.files?.[0])}
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