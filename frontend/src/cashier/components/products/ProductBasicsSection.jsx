import { Input } from "@/cashier/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { Textarea } from "@/cashier/components/ui/textarea";
import FormField from "@/cashier/components/products/FormField";
import { DOT, GRID2, INPUT, SECTION, SECTION_HEAD, SECTION_TITLE, SELECT_TRIGGER, TEXTAREA } from "@/cashier/components/products/formStyles";
import { brands, categories } from "@/cashier/lib/mockData";

const SIZE_PRESETS = [
  { key: "clothing", label: "ملابس (S — XXL)" },
  { key: "kids", label: "مقاسات أطفال" },
  { key: "shoes", label: "مقاسات أحذية" },
  { key: "one", label: "مقاس واحد" },
];

// بيانات الموديل الأساسية: الاسم والفئة والعلامة ونظام المقاسات والوصف.
export default function ProductBasicsSection({ form, onPatch, sizePreset, onSizePresetChange }) {
  return (
    <div className={SECTION}>
      <div className={SECTION_HEAD}>
        <span className={DOT} />
        <h2 className={SECTION_TITLE}>بيانات الموديل</h2>
      </div>

      <div className={GRID2}>
        <FormField label="اسم الموديل">
          <Input value={form.name} onChange={(e) => onPatch({ name: e.target.value })} placeholder="مثال: فستان ورد" className={INPUT} />
        </FormField>

        <FormField label="الفئة">
          <Select value={form.category} onValueChange={(v) => onPatch({ category: v })}>
            <SelectTrigger className={SELECT_TRIGGER}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {categories.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>

        <FormField label="العلامة التجارية">
          <Select value={form.brand} onValueChange={(v) => onPatch({ brand: v })}>
            <SelectTrigger className={SELECT_TRIGGER}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {brands.map((b) => (
                <SelectItem key={b} value={b}>
                  {b}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>

        <FormField label="نظام المقاسات">
          <Select value={sizePreset} onValueChange={onSizePresetChange}>
            <SelectTrigger className={SELECT_TRIGGER}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SIZE_PRESETS.map((p) => (
                <SelectItem key={p.key} value={p.key}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </div>

      <FormField label="الوصف">
        <Textarea
          value={form.description}
          onChange={(e) => onPatch({ description: e.target.value })}
          rows={3}
          placeholder="خامة، طريقة الغسيل، ملاحظات الجودة…"
          className={TEXTAREA}
        />
      </FormField>
    </div>
  );
}