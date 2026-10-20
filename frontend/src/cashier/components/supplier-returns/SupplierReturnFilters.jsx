import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { suppliers } from "@/cashier/lib/mockData";
import { SUPPLIER_RETURN_SETTLEMENTS } from "@/cashier/lib/format";

// فلاتر جدول مرتجعات الموردين: بحث، المورد، وطريقة تسوية الحساب.
export default function SupplierReturnFilters({ term, onTerm, supplierId, onSupplier, settlement, onSettlement, onReset }) {
  const activeCount = [supplierId, settlement].filter(Boolean).length + (term ? 1 : 0);

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
          <Label className={FIELD_LABEL}>بحث بالرقم أو المورد أو الصنف</Label>
          <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="SR-2026-0101، شركة النيل، تيشيرت..." className={FIELD} />
        </div>

        <div>
          <Label className={FIELD_LABEL}>المورد</Label>
          <Select value={supplierId || "all"} onValueChange={onSupplier}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل الموردين" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الموردين</SelectItem>
              {suppliers.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className={FIELD_LABEL}>تسوية الحساب</Label>
          <Select value={settlement || "all"} onValueChange={onSettlement}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل التسويات" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل التسويات</SelectItem>
              {Object.entries(SUPPLIER_RETURN_SETTLEMENTS).map(([key, item]) => (
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