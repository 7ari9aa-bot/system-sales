import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { PAYMENT_LABEL, RECEIPT_LABEL } from "@/cashier/api/purchasingAdapter";

function Pick({ label, value, onChange, allLabel, options }) {
  return (
    <div>
      <Label className={FIELD_LABEL}>{label}</Label>
      <Select value={value || "all"} onValueChange={onChange}>
        <SelectTrigger className={FIELD_SELECT}>
          <SelectValue placeholder={allLabel} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{allLabel}</SelectItem>
          {options.map(([key, text]) => (
            <SelectItem key={key} value={key}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

// فلاتر جدول المشتريات: بحث، المورد، حالة الاستلام، وحالة الدفع (منفصلتين).
export default function PurchaseFilters({ term, onTerm, supplierId, onSupplier, receipt, onReceipt, payment, onPayment, onReset, suppliers = [] }) {
  const activeCount = [supplierId, receipt, payment].filter(Boolean).length + (term ? 1 : 0);

  return (
    <FilterPanel className={FILTER_PANEL} headerClassName={FILTER_PANEL_HEADER} contentClassName={FILTER_PANEL_CONTENT} activeCount={activeCount} onReset={onReset}>
      <div className="grid gap-3 sm:grid-cols-4">
        <div>
          <Label className={FIELD_LABEL}>بحث برقم الفاتورة أو المورد</Label>
          <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="PO-2026-0001، شركة النيل..." className={FIELD} />
        </div>
        <Pick label="المورد" value={supplierId} onChange={onSupplier} allLabel="كل الموردين" options={suppliers.map((s) => [s.id, s.name])} />
        <Pick label="حالة الاستلام" value={receipt} onChange={onReceipt} allLabel="كل الحالات" options={Object.entries(RECEIPT_LABEL)} />
        <Pick label="حالة الدفع" value={payment} onChange={onPayment} allLabel="كل الحالات" options={Object.entries(PAYMENT_LABEL)} />
      </div>
    </FilterPanel>
  );
}
