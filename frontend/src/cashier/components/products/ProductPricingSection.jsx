import { Input } from "@/cashier/components/ui/input";
import FormField from "@/cashier/components/products/FormField";
import { DOT, GRID3, INPUT, SECTION, SECTION_HEAD, SECTION_TITLE } from "@/cashier/components/products/formStyles";

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

        <FormField label="حد التنبيه عند انخفاض المخزون">
          <Input type="number" value={form.threshold} min={0} step="1" onChange={(e) => onPatch({ threshold: e.target.value })} className={`${INPUT} num`} />
        </FormField>
      </div>
    </div>
  );
}