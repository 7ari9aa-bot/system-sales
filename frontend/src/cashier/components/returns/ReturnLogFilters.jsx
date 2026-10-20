import { Search } from "lucide-react";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { REFUND_METHODS, RETURN_STATUS } from "@/cashier/lib/format";

// فلاتر سجل المرتجعات: بحث، طريقة الاسترداد، والحالة.
export default function ReturnLogFilters({ term, onTerm, refund, onRefund, status, onStatus, onReset }) {
  const activeCount = [refund, status].filter(Boolean).length + (term ? 1 : 0);

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
          <Label className={FIELD_LABEL}>بحث برقم المرتجع أو الفاتورة أو العميل</Label>
          <div className="relative">
            <Search className="pointer-events-none absolute right-1.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#7A766C]" />
            <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="RET-2026-0012، INV-2026-0065" className={`${FIELD} ps-6`} />
          </div>
        </div>

        <div>
          <Label className={FIELD_LABEL}>طريقة الاسترداد</Label>
          <Select value={refund || "all"} onValueChange={onRefund}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل الطرق" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الطرق</SelectItem>
              {Object.entries(REFUND_METHODS).map(([key, m]) => (
                <SelectItem key={key} value={key}>
                  {m.label}
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
              {Object.entries(RETURN_STATUS).map(([key, s]) => (
                <SelectItem key={key} value={key}>
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