import { Search } from "lucide-react";
import { Input } from "@/applications/apparel/components/ui/input";
import { Label } from "@/applications/apparel/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/applications/apparel/components/ui/select";
import FilterPanel from "@/applications/apparel/components/ui-kit/FilterPanel";
import { INVENTORY_STATUS } from "@/applications/apparel/lib/format";

const FIELD =
  "h-10 rounded-[10px] border-[#C7C2B8] bg-[#FBFAF7] px-3 text-[13px] text-[#3B3A36] transition-[border-color,box-shadow] duration-200 hover:border-[#E8761A] focus-visible:border-[#E8761A] focus-visible:ring-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#E8761A]";
const FIELD_LABEL = "mb-1.5 block text-[11px] font-medium text-[#7A766C]";

/** One pick-one filter: "all" is the empty value, so choosing it clears the filter. */
function Pick({ label, allLabel, value, onChange, options }) {
  return (
    <div>
      <Label className={FIELD_LABEL}>{label}</Label>
      <Select value={value || "all"} onValueChange={(v) => onChange(v === "all" ? "" : v)}>
        <SelectTrigger className={FIELD}>
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
 * The stock screen's filters: search, category, brand, season, material (fabric) and stock status.
 * Pure: the page owns the values and the lists, so what is drawn is exactly what is passed in.
 */
export default function StockFilters({ values, onChange, categories = [], brands = [], seasons = [], materials = [] }) {
  const { term = "", category = "", brand = "", season = "", material = "", status = "" } = values;
  const set = (key) => (v) => onChange({ ...values, [key]: v });
  return (
    <FilterPanel
      className="animate-inv-rise rounded-[14px] border-[#E3DED4] bg-white [animation-delay:.2s]"
      activeCount={[category, brand, season, material, status].filter(Boolean).length + (term ? 1 : 0)}
      onReset={() => onChange({ term: "", category: "", brand: "", season: "", material: "", status: "" })}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <Label className={FIELD_LABEL}>بحث بالمنتج أو الكود أو الباركود</Label>
          <div className="relative">
            <Search className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9A958A]" />
            <Input value={term} onChange={(e) => set("term")(e.target.value)} placeholder="بنطلون جينز، SKU-0003" className={`pe-10 ${FIELD}`} />
          </div>
        </div>
        <Pick label="التصنيف" allLabel="كل التصنيفات" value={category} onChange={set("category")} options={categories.map((c) => ({ value: c.id, label: c.name }))} />
        <Pick label="العلامة التجارية" allLabel="كل العلامات" value={brand} onChange={set("brand")} options={brands.map((b) => ({ value: b.id, label: b.name }))} />
        <Pick label="الموسم" allLabel="كل المواسم" value={season} onChange={set("season")} options={seasons.map((name) => ({ value: name, label: name }))} />
        <Pick label="الخامة" allLabel="كل الخامات" value={material} onChange={set("material")} options={materials.map((name) => ({ value: name, label: name }))} />
        <Pick label="حالة الرصيد" allLabel="كل الحالات" value={status} onChange={set("status")} options={Object.entries(INVENTORY_STATUS).map(([key, st]) => ({ value: key, label: st.label }))} />
      </div>
    </FilterPanel>
  );
}
