import { Wand2 } from "lucide-react";
import FormField from "@/applications/apparel/components/products/FormField";
import { CHIP, CHIP_ON, CHIPS, DOT, PRIMARY_BTN, SECTION, SECTION_HEAD, SECTION_TITLE, SWATCH_DOT } from "@/applications/apparel/components/products/formStyles";
import { useShopOptions } from "@/applications/apparel/api/useShopOptions";
import { cn } from "@/applications/apparel/lib/utils";

// اختيار الألوان والمقاسات ثم توليد جدول التركيبات.
export default function ProductVariantsPicker({ colors, onToggleColor, sizes, onToggleSize, presetSizes, canGenerate, onGenerate }) {
  const { options } = useShopOptions();
  return (
    <div className={SECTION}>
      <div className={SECTION_HEAD}>
        <span className={DOT} />
        <h2 className={SECTION_TITLE}>الألوان والمقاسات</h2>
      </div>

      <FormField label="الألوان المتاحة">
        <div className={CHIPS}>
          {options.colours.map((c) => (
            <button
              key={c.name}
              type="button"
              aria-pressed={colors.includes(c.name)}
              onClick={() => onToggleColor(c.name)}
              className={cn(CHIP, "group", colors.includes(c.name) && CHIP_ON)}
            >
              <span className={SWATCH_DOT} style={{ backgroundColor: c.hex ?? "#A1A1AA" }} />
              {c.name}
            </button>
          ))}
        </div>
      </FormField>

      <FormField label="المقاسات">
        <div className={CHIPS}>
          {presetSizes.map((s) => (
            <button key={s} type="button" aria-pressed={sizes.includes(s)} onClick={() => onToggleSize(s)} className={cn(CHIP, sizes.includes(s) && CHIP_ON)}>
              {s}
            </button>
          ))}
        </div>
      </FormField>

      <button type="button" className={`${PRIMARY_BTN} self-start`} disabled={!canGenerate} onClick={onGenerate}>
        <Wand2 className="h-4 w-4" />
        توليد جدول المتغيرات ({colors.length} لون × {sizes.length} مقاس)
      </button>
    </div>
  );
}