import { Search } from "lucide-react";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { MOVEMENT_TYPES } from "@/cashier/lib/format";

// فلاتر حركة الأصناف: بحث، نوع الحركة، ونطاق التاريخ.
export default function MovementFilters({ term, onTerm, type, onType, from, onFrom, to, onTo, onReset }) {
  const activeCount = [type, from, to].filter(Boolean).length + (term ? 1 : 0);

  return (
    <FilterPanel
      className={FILTER_PANEL}
      headerClassName={FILTER_PANEL_HEADER}
      contentClassName={FILTER_PANEL_CONTENT}
      activeCount={activeCount}
      onReset={onReset}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <Label className={FIELD_LABEL}>بحث بالمنتج أو المستند</Label>
          <div className="relative">
            <Search className="pointer-events-none absolute right-1.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#7A766C]" />
            <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="INV-2026-0064، SKU-0003" className={`${FIELD} ps-6`} />
          </div>
        </div>

        <div>
          <Label className={FIELD_LABEL}>نوع الحركة</Label>
          <Select value={type || "all"} onValueChange={onType}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل الأنواع" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الأنواع</SelectItem>
              {Object.entries(MOVEMENT_TYPES).map(([key, t]) => (
                <SelectItem key={key} value={key}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className={FIELD_LABEL}>من تاريخ</Label>
          <Input type="date" value={from} onChange={(e) => onFrom(e.target.value)} className={FIELD} />
        </div>

        <div>
          <Label className={FIELD_LABEL}>إلى تاريخ</Label>
          <Input type="date" value={to} onChange={(e) => onTo(e.target.value)} className={FIELD} />
        </div>
      </div>
    </FilterPanel>
  );
}