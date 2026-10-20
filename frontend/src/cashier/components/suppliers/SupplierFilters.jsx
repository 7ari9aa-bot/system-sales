import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { SUPPLIER_STATUS } from "@/cashier/lib/format";

// فلاتر جدول الموردين: بحث، مدينة، وحالة المورد.
export default function SupplierFilters({ term, onTerm, city, onCity, status, onStatus, onReset, cities = [] }) {
  const activeCount = [city, status].filter(Boolean).length + (term ? 1 : 0);

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
          <Label className={FIELD_LABEL}>بحث بالاسم أو المسؤول أو الهاتف</Label>
          <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="شركة النيل، أيمن خليل، 0100..." className={FIELD} />
        </div>

        <div>
          <Label className={FIELD_LABEL}>المدينة</Label>
          <Select value={city || "all"} onValueChange={onCity}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل المدن" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل المدن</SelectItem>
              {cities.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className={FIELD_LABEL}>الحالة</Label>
          <Select value={status || "all"} onValueChange={onStatus}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل الحالات" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الحالات</SelectItem>
              {Object.entries(SUPPLIER_STATUS).map(([key, item]) => (
                <SelectItem key={key} value={key}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </FilterPanel>
  );
}