import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { PURCHASE_STATUSES } from "@/cashier/lib/purchasesData";
import { supplierRows } from "@/cashier/lib/opsData";

// فلاتر جدول المشتريات: بحث برقم الفاتورة، المورد، وحالة السداد.
export default function PurchaseFilters({ term, onTerm, supplierId, onSupplier, status, onStatus, onReset }) {
  const activeCount = [supplierId, status].filter(Boolean).length + (term ? 1 : 0);

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
          <Label className={FIELD_LABEL}>بحث برقم الفاتورة أو المورد</Label>
          <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="PO-2026-0118، شركة النيل..." className={FIELD} />
        </div>

        <div>
          <Label className={FIELD_LABEL}>المورد</Label>
          <Select value={supplierId || "all"} onValueChange={onSupplier}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل الموردين" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الموردين</SelectItem>
              {supplierRows.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className={FIELD_LABEL}>حالة السداد</Label>
          <Select value={status || "all"} onValueChange={onStatus}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل الحالات" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الحالات</SelectItem>
              {PURCHASE_STATUSES.map((s) => (
                <SelectItem key={s.key} value={s.key}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </FilterPanel>
  );
}