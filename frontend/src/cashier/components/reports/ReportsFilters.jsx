import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { PERIODS } from "@/cashier/lib/uiConstants";

// فلاتر التقارير: الفترة الزمنية. (فلتر التصنيف يعود مع تقارير الأصناف والأرباح والمخزون حين تُربط بالخادم.)
export default function ReportsFilters({ period, onPeriod, onReset }) {
  const activeCount = 1;

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
      </div>
    </FilterPanel>
  );
}