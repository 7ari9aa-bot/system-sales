import { Search } from "lucide-react";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";

// فلاتر سجل المرتجعات: بحث ومدى تاريخ فقط (الخادم لا يسجل العميل أو السبب أو طريقة الاسترداد على المرتجع).
export default function ReturnLogFilters({ term, onTerm, from, onFrom, to, onTo, onReset }) {
  const activeCount = [from, to].filter(Boolean).length + (term ? 1 : 0);
  return (
    <FilterPanel className={FILTER_PANEL} headerClassName={FILTER_PANEL_HEADER} contentClassName={FILTER_PANEL_CONTENT} activeCount={activeCount} onReset={onReset}>
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <Label className={FIELD_LABEL}>بحث برقم المرتجع أو الفاتورة الأصلية</Label>
          <div className="relative">
            <Search className="pointer-events-none absolute right-1.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#7A766C]" />
            <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="POS-RET-… أو POS-…" className={`${FIELD} ps-6`} aria-label="بحث في المرتجعات" />
          </div>
        </div>
        <div>
          <Label className={FIELD_LABEL}>من تاريخ</Label>
          <Input type="date" value={from} onChange={(e) => onFrom(e.target.value)} className={FIELD} aria-label="من تاريخ" />
        </div>
        <div>
          <Label className={FIELD_LABEL}>إلى تاريخ</Label>
          <Input type="date" value={to} onChange={(e) => onTo(e.target.value)} className={FIELD} aria-label="إلى تاريخ" />
        </div>
      </div>
    </FilterPanel>
  );
}
