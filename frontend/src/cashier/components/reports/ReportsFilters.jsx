import { Tag } from "lucide-react";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { categories } from "@/cashier/lib/mockData";
import { PERIODS } from "@/cashier/lib/opsData";

// فلاتر التقارير: الفترة الزمنية وتصنيف المنتجات.
export default function ReportsFilters({ period, onPeriod, category, onCategory, onReset }) {
  const activeCount = [category].filter(Boolean).length + 1;

  return (
    <FilterPanel
      className={FILTER_PANEL}
      headerClassName={FILTER_PANEL_HEADER}
      contentClassName={FILTER_PANEL_CONTENT}
      activeCount={activeCount}
      onReset={onReset}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <Label className={FIELD_LABEL}>الفترة</Label>
          <Select value={period} onValueChange={onPeriod}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PERIODS.map((p) => (
                <SelectItem key={p.key} value={p.key}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className={FIELD_LABEL}>التصنيف</Label>
          <Select value={category || "all"} onValueChange={onCategory}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل التصنيفات" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل التصنيفات</SelectItem>
              {categories.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-end">
          <p className="flex items-center gap-1.5 text-[11px] text-[#7A766C]">
            <Tag className="h-3.5 w-3.5" />
            التصنيف يؤثر على تقارير الأصناف والأرباح والمخزون فقط.
          </p>
        </div>
      </div>
    </FilterPanel>
  );
}