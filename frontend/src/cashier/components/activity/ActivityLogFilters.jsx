import { Search } from "lucide-react";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { ACTIVITY_TYPES } from "@/cashier/lib/format";

// فلاتر سجل العمليات: بحث برقم المستند أو التفاصيل أو الموظف، نوع العملية، الموظف، ونطاق التاريخ.
// كلها تُرسل للسيرفر، فالفلتر يصل لعمليات أقدم من المعروض حاليًا.
export default function ActivityLogFilters({ term, onTerm, type, onType, employee, onEmployee, employeesList, from, onFrom, to, onTo, onReset }) {
  const activeCount = [type, employee, from, to].filter(Boolean).length + (term ? 1 : 0);

  return (
    <FilterPanel
      className={FILTER_PANEL}
      headerClassName={FILTER_PANEL_HEADER}
      contentClassName={FILTER_PANEL_CONTENT}
      activeCount={activeCount}
      onReset={onReset}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div className="sm:col-span-2 lg:col-span-3">
          <Label className={FIELD_LABEL}>بحث برقم المستند أو التفاصيل أو الموظف</Label>
          <div className="relative">
            <Search className="pointer-events-none absolute right-1.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#7A766C]" />
            <Input value={term} onChange={(e) => onTerm(e.target.value)} placeholder="POS-RET، مورد، منى" className={`${FIELD} ps-6`} />
          </div>
        </div>

        <div>
          <Label className={FIELD_LABEL}>نوع العملية</Label>
          <Select value={type || "all"} onValueChange={onType}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل العمليات" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل العمليات</SelectItem>
              {Object.entries(ACTIVITY_TYPES).map(([key, t]) => (
                <SelectItem key={key} value={key}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className={FIELD_LABEL}>الموظف</Label>
          <Select value={employee || "all"} onValueChange={onEmployee}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل الموظفين" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الموظفين</SelectItem>
              {employeesList.map((e) => (
                <SelectItem key={e.id} value={e.id}>
                  {e.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className={FIELD_LABEL}>من تاريخ</Label>
            <Input type="date" value={from} max={to || undefined} onChange={(e) => onFrom(e.target.value)} className={FIELD} />
          </div>
          <div>
            <Label className={FIELD_LABEL}>إلى تاريخ</Label>
            <Input type="date" value={to} min={from || undefined} onChange={(e) => onTo(e.target.value)} className={FIELD} />
          </div>
        </div>
      </div>
    </FilterPanel>
  );
}
