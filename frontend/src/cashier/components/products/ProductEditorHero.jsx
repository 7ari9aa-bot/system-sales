import { Printer } from "lucide-react";
import { Image } from "@/cashier/components/ui/image";
import { HERO, HERO_BAR, HERO_BTN, HERO_MEDIA, HERO_SCRIM } from "@/cashier/components/products/formStyles";

const HERO_BG = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/9f08bfb9b_generated_f96caf77.jpg";

// رأس الشاشة: صورة الموديل كخلفية، طبقة تدرّج، عنوان الشاشة وشريط الأزرار.
export default function ProductEditorHero({ title, subtitle, sku, canPrint, onPrintLabels }) {
  return (
    <div className={HERO}>
      <Image src={HERO_BG} alt="" fittingType="fill" className={HERO_MEDIA} />
      <div className={HERO_SCRIM} />

      <div className="relative z-[2]">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-heading text-[26px] font-extrabold leading-[1.2] tracking-[-.03em] text-[#2a2622] sm:text-[32px]">{title}</h1>
          {sku && <span className="num rounded-lg border border-[#d9d4cd] bg-white/70 px-2.5 py-1 text-xs font-semibold text-[#6b6358]">{sku}</span>}
        </div>
        <p className="mt-1.5 max-w-[760px] text-[14px] text-[#6b6358]">{subtitle}</p>

        <div className={HERO_BAR}>
          <button type="button" className={HERO_BTN} disabled={!canPrint} onClick={onPrintLabels}>
            <Printer className="h-[18px] w-[18px]" />
            طباعة الباركودات
          </button>
        </div>
      </div>
    </div>
  );
}