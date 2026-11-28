import { Input } from "@/applications/apparel/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/applications/apparel/components/ui/select";
import { Textarea } from "@/applications/apparel/components/ui/textarea";
import FormField from "@/applications/apparel/components/products/FormField";
import { DOT, GRID2, INPUT, SECTION, SECTION_HEAD, SECTION_TITLE, SELECT_TRIGGER, TEXTAREA } from "@/applications/apparel/components/products/formStyles";
import NamedPicker from "@/applications/apparel/components/products/NamedPicker";
import { useBrands, useCategories, useCreateBrand, useCreateCategory } from "@/applications/apparel/api/useCatalogWrite";
import { useShopOptions } from "@/applications/apparel/api/useShopOptions";
import { resolveSizePreset, sizePresetChoices } from "@/applications/apparel/lib/shopOptions";
import { MATERIAL_MAX_LENGTH } from "@/applications/apparel/lib/material";

// معرّف قائمة اقتراحات الخامة. ثابت لأن الخانة واحدة في الصفحة، والاقتراحات نفسها بتيجي من
// خامات المحل اللي استخدمها فعلاً (زي ما المواسم بتيجي من مواسم المحل).
const MATERIAL_LIST_ID = "product-material-options";


// بيانات الموديل الأساسية: الاسم والفئة والعلامة والموسم والخامة ونظام المقاسات والوصف.
// `materials` هي خامات المحل نفسه (نصوص) اللي بتتعرض كاقتراحات في خانة الخامة؛ الخانة نفسها
// نص حر، فصاحب المتجر يقدر يكتب خامة جديدة من غير ما يختار من القائمة.
export default function ProductBasicsSection({ form, onPatch, sizePreset, onSizePresetChange, materials = [] }) {
  const { options } = useShopOptions();
  const sizeChoices = sizePresetChoices(options.sizeSets);
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

        <FormField label="الموسم">
          <Input
            value={form.season ?? ""}
            onChange={(e) => onPatch({ season: e.target.value })}
            maxLength={40}
            placeholder="مثال: صيف 26"
            className={INPUT}
          />
        </FormField>

        <FormField label="الخامة">
          <Input
            value={form.material ?? ""}
            onChange={(e) => onPatch({ material: e.target.value })}
            maxLength={MATERIAL_MAX_LENGTH}
            list={MATERIAL_LIST_ID}
            placeholder="مثال: قطن"
            className={INPUT}
          />
          <datalist id={MATERIAL_LIST_ID}>
            {materials.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </FormField>

        <FormField label="نظام المقاسات">
          <Select value={resolveSizePreset(options.sizeSets, sizePreset)} onValueChange={onSizePresetChange}>
            <SelectTrigger className={SELECT_TRIGGER}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {sizeChoices.map((p) => (
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
          placeholder="طريقة الغسيل، ملاحظات الجودة، تفاصيل القصّة…"
          className={TEXTAREA}
        />
      </FormField>
    </div>
  );
}