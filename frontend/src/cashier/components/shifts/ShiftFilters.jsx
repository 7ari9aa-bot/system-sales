import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";

// فلاتر جدول الورديات: الموظف وحالة الوردية.
export default function ShiftFilters({ employees = [], employee, onEmployee, status, onStatus, onReset }) {
  const activeCount = [employee, status].filter(Boolean).length;

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
          <Label className={FIELD_LABEL}>الموظف</Label>
          <Select value={employee || "all"} onValueChange={onEmployee}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل الموظفين" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الموظفين</SelectItem>
              {employees.map((e) => (
                <SelectItem key={e.id} value={e.id}>
                  {e.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className={FIELD_LABEL}>حالة الوردية</Label>
          <Select value={status || "all"} onValueChange={onStatus}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل الحالات" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الحالات</SelectItem>
              <SelectItem value="open">مفتوحة</SelectItem>
              <SelectItem value="closed">مغلقة</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-end">
          <p className="text-[11px] leading-relaxed text-[#7A766C]">النقدية المتوقعة = رصيد البداية + المبيعات النقدية − المرتجعات − المصروفات النقدية.</p>
        </div>
      </div>
    </FilterPanel>
  );
}