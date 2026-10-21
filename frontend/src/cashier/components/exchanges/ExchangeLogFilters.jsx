import { Search } from "lucide-react";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { SETTLEMENT_TYPES } from "@/cashier/lib/format";

// فلاتر سجل الاستبدال: بحث، نوع التسوية، والحالة.
export default function ExchangeLogFilters({ term, onTerm, settlement, onSettlement, onReset }) {
  const activeCount = [settlement].filter(Boolean).length + (term ? 1 : 0);

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
          <Label className={FIELD_LABEL}>بحث برقم الاستبدال أو الفاتورة أو العميل</Label>
          <div className="relative">
            <Search className="pointer-events-none absolute right-1.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#7A766C]" />
            <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="رقم الاستبدال أو الفاتورة أو الصنف" className={`${FIELD} ps-6`} />
          </div>
        </div>

        <div>
          <Label className={FIELD_LABEL}>نوع التسوية</Label>
          <Select value={settlement || "all"} onValueChange={onSettlement}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل التسويات" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل التسويات</SelectItem>
              {Object.entries(SETTLEMENT_TYPES).map(([key, s]) => (
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