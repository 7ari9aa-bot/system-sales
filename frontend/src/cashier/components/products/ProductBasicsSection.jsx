import { Input } from "@/cashier/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { Textarea } from "@/cashier/components/ui/textarea";
import FormField from "@/cashier/components/products/FormField";
import { DOT, GRID2, INPUT, SECTION, SECTION_HEAD, SECTION_TITLE, SELECT_TRIGGER, TEXTAREA } from "@/cashier/components/products/formStyles";
import NamedPicker from "@/cashier/components/products/NamedPicker";
import { useBrands, useCategories, useCreateBrand, useCreateCategory } from "@/cashier/api/useCatalogWrite";

const SIZE_PRESETS = [
  { key: "clothing", label: "ملابس (S — XXL)" },
  { key: "kids", label: "مقاسات أطفال" },
  { key: "shoes", label: "مقاسات أحذية" },
  { key: "one", label: "مقاس واحد" },
];

// بيانات الموديل الأساسية: الاسم والفئة والعلامة ونظام المقاسات والوصف.
export default function ProductBasicsSection({ form, onPatch, sizePreset, onSizePresetChange }) {
  const categories = useCategories();
  const brands = useBrands();
  const createCategory = useCreateCategory();
  const createBrand = useCreateBrand();
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
          <NamedPicker
            items={categories.data ?? []}
            loading={categories.isLoading}
            value={form.categoryId}
            onChange={(id) => onPatch({ categoryId: id })}
            onCreate={(name) => createCategory.mutateAsync(name)}
            noneLabel="بدون فئة"
            addLabel="+ فئة جديدة"
            placeholder="اسم الفئة"
          />
        </FormField>

        <FormField label="العلامة التجارية">
          <NamedPicker
            items={brands.data ?? []}
            loading={brands.isLoading}
            value={form.brandId}
            onChange={(id) => onPatch({ brandId: id })}
            onCreate={(name) => createBrand.mutateAsync(name)}
            noneLabel="بدون علامة"
            addLabel="+ علامة جديدة"
            placeholder="اسم العلامة"
          />
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