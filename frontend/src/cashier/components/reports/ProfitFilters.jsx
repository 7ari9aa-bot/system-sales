import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";

/** One pick-one filter: "all" is the empty value, so choosing it clears the filter. */
function Pick({ label, allLabel, value, onChange, options }) {
  return (
    <div>
      <Label className={FIELD_LABEL}>{label}</Label>
      <Select value={value || "all"} onValueChange={(v) => onChange(v === "all" ? "" : v)}>
        <SelectTrigger className={FIELD_SELECT}>
          <SelectValue placeholder={allLabel} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{allLabel}</SelectItem>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/**
 * فلاتر تقرير الربح: العلامة التجارية والموسم والخامة. الفترة في لوحة الفلاتر العليا لأنها مشتركة
 * بين كل التقارير، فمش بتتكرر هنا. المكوّن نقي: الصفحة بتملك القيم والقوائم، فاللي بيتعرض هو
 * بالظبط اللي بيتسلّم — و"all" بتترجع قيمة فاضية، يعني الفلتر اتشال.
 */
export default function ProfitFilters({ values, onChange, brands = [], seasons = [], materials = [] }) {
  const { brand = "", season = "", material = "" } = values ?? {};
  const set = (key) => (v) => onChange({ ...values, [key]: v });

  return (
    <FilterPanel
      className={FILTER_PANEL}
      headerClassName={FILTER_PANEL_HEADER}
      contentClassName={FILTER_PANEL_CONTENT}
      activeCount={[brand, season, material].filter(Boolean).length}
      onReset={() => onChange({ brand: "", season: "", material: "" })}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Pick
          label="العلامة التجارية"
          allLabel="كل العلامات"
          value={brand}
          onChange={set("brand")}
          options={brands.map((b) => ({ value: b.id, label: b.name }))}
        />
        <Pick
          label="الموسم"
          allLabel="كل المواسم"
          value={season}
          onChange={set("season")}
          options={seasons.map((name) => ({ value: name, label: name }))}
        />
        <Pick
          label="الخامة"
          allLabel="كل الخامات"
          value={material}
          onChange={set("material")}
          options={materials.map((name) => ({ value: name, label: name }))}
        />
      </div>
    </FilterPanel>
  );
}
