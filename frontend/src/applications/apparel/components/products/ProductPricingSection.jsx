import { Input } from "@/applications/apparel/components/ui/input";
import FormField from "@/applications/apparel/components/products/FormField";
import { DOT, GRID3, INPUT, SECTION, SECTION_HEAD, SECTION_TITLE } from "@/applications/apparel/components/products/formStyles";

// الأسعار الافتراضية وحد التنبيه التي تُطبَّق على كل تركيبات الموديل.
export default function ProductPricingSection({ form, onPatch }) {
  return (
    <div className={SECTION}>
      <div className={SECTION_HEAD}>
        <span className={DOT} />
        <h2 className={SECTION_TITLE}>الأسعار والتنبيه</h2>
      </div>

      <div className={GRID3}>
        <FormField label="سعر البيع الافتراضي">
          <Input type="number" value={form.sellPrice} min={0} step="0.01" placeholder="مثال: 450" onChange={(e) => onPatch({ sellPrice: e.target.value })} className={`${INPUT} num`} />
        </FormField>

        <FormField label="تكلفة الوحدة (للرصيد الافتتاحي)">
          <Input
            type="number"
            value={form.unitCost ?? ""}
            min={0}
            step="0.01"
            placeholder="تسيبها فاضية = تكلفة مجهولة"
            onChange={(e) => onPatch({ unitCost: e.target.value })}
            className={`${INPUT} num`}
          />
        </FormField>

        <FormField label="حد التنبيه عند انخفاض المخزون">
          <Input type="number" value={form.threshold} min={0} step="1" onChange={(e) => onPatch({ threshold: e.target.value })} className={`${INPUT} num`} />
        </FormField>
      </div>
    </div>
  );
}