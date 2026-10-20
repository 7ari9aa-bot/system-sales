import { Search } from "lucide-react";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { PAYMENT_METHODS } from "@/cashier/lib/format";

// فلاتر جدول المصروفات: بحث، التصنيف، وطريقة الدفع.
export default function ExpenseFilters({ term, onTerm, category, onCategory, payment, onPayment, onReset, categories, methods }) {
  const activeCount = [category, payment].filter(Boolean).length + (term ? 1 : 0);

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
          <Label className={FIELD_LABEL}>بحث بالبيان أو رقم المصروف أو الموظف</Label>
          <div className="relative">
            <Search className="pointer-events-none absolute right-1.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#7A766C]" />
            <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="كهرباء، EXP-1041، منى" className={`${FIELD} ps-6`} />
          </div>
        </div>

        <div>
          <Label className={FIELD_LABEL}>التصنيف</Label>
          <Select value={category || "all"} onValueChange={onCategory}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل التصنيفات" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل التصنيفات</SelectItem>
              {categories.map((c) => (
                <SelectItem key={c.id} value={c.name}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className={FIELD_LABEL}>طريقة الدفع</Label>
          <Select value={payment || "all"} onValueChange={onPayment}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل الطرق" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الطرق</SelectItem>
              {methods.map((p) => (
                <SelectItem key={p} value={p}>
                  {PAYMENT_METHODS[p]?.label ?? p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </FilterPanel>
  );
}