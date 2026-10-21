import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { RETURN_STATUS_LABEL, SETTLEMENT_LABEL } from "@/cashier/api/purchasingAdapter";

const pick = (value, set) => set(value === "all" ? "" : value);

// فلاتر مرتجعات الموردين: بحث، المورد، التسوية، وقرار المورد.
export default function SupplierReturnFilters({ term, onTerm, supplierId, onSupplier, settlement, onSettlement, status, onStatus, onReset, suppliers = [] }) {
  const activeCount = [term.trim(), supplierId, settlement, status].filter(Boolean).length;
  const select = (label, value, onChange, all, options) => (
    <div>
      <Label className={FIELD_LABEL}>{label}</Label>
      <Select value={value || "all"} onValueChange={(v) => pick(v, onChange)}>
        <SelectTrigger className={FIELD_SELECT}>
          <SelectValue placeholder={all} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{all}</SelectItem>
          {options.map(([k, text]) => (
            <SelectItem key={k} value={k}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
  return (
    <FilterPanel className={FILTER_PANEL} headerClassName={FILTER_PANEL_HEADER} contentClassName={FILTER_PANEL_CONTENT} activeCount={activeCount} onReset={onReset}>
      <div className="grid gap-3 sm:grid-cols-4">
      <div>
        <Label className={FIELD_LABEL}>بحث برقم المرتجع أو المورد أو الصنف</Label>
        <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="SR-2026-0001، شركة النيل..." className={FIELD} />
      </div>
      {select("المورد", supplierId, onSupplier, "كل الموردين", suppliers.map((s) => [s.id, s.name]))}
      {select("التسوية", settlement, onSettlement, "كل التسويات", Object.entries(SETTLEMENT_LABEL))}
      {select("قرار المورد", status, onStatus, "كل الحالات", Object.entries(RETURN_STATUS_LABEL))}
      </div>
    </FilterPanel>
  );
}
