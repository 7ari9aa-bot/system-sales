import { Search, X } from "lucide-react";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { INVOICE_STATUS, PAYMENT_METHODS } from "@/cashier/lib/format";

// ما يدعمه الخادم فقط: «مقسّم» لفواتير الدفع المتعدد، وبدون «آجل» و«معلقة» و«ملغاة» (لا توجد كإيصالات بيع).
export const SALES_PAYMENT_OPTIONS = { cash: PAYMENT_METHODS.cash, card: PAYMENT_METHODS.card, wallet: PAYMENT_METHODS.wallet, mixed: { label: "مقسّم (أكثر من طريقة)" } };
export const SALES_STATUS_OPTIONS = { paid: INVOICE_STATUS.paid, partial_return: INVOICE_STATUS.partial_return, returned: INVOICE_STATUS.returned };
import { cn } from "@/cashier/lib/utils";

const LABEL = "mb-[5px] block text-[11px] font-semibold text-[#7a6f61]";
const FIELD =
  "num h-[38px] w-full rounded-[9px] border border-[#e3d6c2] bg-[#FFFDFA] px-3 text-[13px] text-[#0F172A] shadow-none transition-[border-color,box-shadow] duration-150 hover:border-[#F97316] focus-visible:border-[#F97316] focus-visible:ring-2 focus-visible:ring-[#F97316]/30 focus-visible:ring-offset-0";
const TRIGGER =
  "num h-[38px] rounded-[9px] border border-[#e3d6c2] bg-[#FFFDFA] px-3 text-[13px] text-[#0F172A] shadow-none transition-[border-color,box-shadow] duration-150 hover:border-[#F97316] focus:border-[#F97316] focus:ring-2 focus:ring-[#F97316]/30 focus:ring-offset-0 data-[state=open]:border-[#F97316] [&>svg]:h-[15px] [&>svg]:w-[15px] [&>svg]:text-[#9a8e7d] [&>svg]:opacity-100";

// شريط تحكّم ملتصق بحد الجدول العلوي: بحث برقم الفاتورة أو الباركود، الفترة، طريقة الدفع، حالة الفاتورة، الموظف.
export default function SalesLogFilters({ filters, onChange, onReset, activeCount = 0, paymentOptions = SALES_PAYMENT_OPTIONS, statusOptions = SALES_STATUS_OPTIONS }) {
  const set = (patch) => onChange({ ...filters, ...patch });

  return (
    <div className="grid animate-bar-drop grid-cols-1 gap-3 rounded-t-[14px] border-[1.5px] border-b-0 border-[#F97316] bg-white px-[18px] pb-[14px] pt-4 sm:grid-cols-2 xl:grid-cols-4">
      <div className="sm:col-span-2">
        <Label className={LABEL} htmlFor="sales-search">
          بحث برقم الفاتورة أو الباركود
        </Label>
        <div className="relative">
          <Search
            className="pointer-events-none absolute right-3 top-1/2 h-[15px] w-[15px] -translate-y-1/2 text-[#9a8e7d]"
            aria-hidden="true"
          />
          <Input
            id="sales-search"
            value={filters.term}
            onChange={(e) => set({ term: e.target.value })}
            placeholder="رقم الفاتورة POS-… • كود الصنف • اسم الصنف"
            className={cn(FIELD, "pr-9 placeholder:text-[#8a7f70]")}
          />
        </div>
      </div>

      <div className="sm:col-span-2">
        <Label className={LABEL}>الفترة</Label>
        <div className="flex items-center gap-2">
          <Input
            type="date"
            value={filters.from}
            onChange={(e) => set({ from: e.target.value })}
            aria-label="من تاريخ"
            className={cn(FIELD, "flex-1")}
          />
          <em className="shrink-0 text-[11px] font-normal not-italic text-[#7a6f61]">إلى</em>
          <Input
            type="date"
            value={filters.to}
            onChange={(e) => set({ to: e.target.value })}
            aria-label="إلى تاريخ"
            className={cn(FIELD, "flex-1")}
          />
        </div>
      </div>

      <div>
        <Label className={LABEL}>طريقة الدفع</Label>
        <Select value={filters.payment || "all"} onValueChange={(v) => set({ payment: v === "all" ? "" : v })}>
          <SelectTrigger className={TRIGGER}>
            <SelectValue placeholder="كل الطرق" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">كل الطرق</SelectItem>
            {Object.entries(paymentOptions).map(([key, m]) => (
              <SelectItem key={key} value={key}>
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label className={LABEL}>حالة الفاتورة</Label>
        <Select value={filters.status || "all"} onValueChange={(v) => set({ status: v === "all" ? "" : v })}>
          <SelectTrigger className={TRIGGER}>
            <SelectValue placeholder="كل الحالات" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">كل الحالات</SelectItem>
            {Object.entries(statusOptions).map(([key, s]) => (
              <SelectItem key={key} value={key}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {activeCount > 0 && (
        <div className="flex items-end">
          <button
            type="button"
            onClick={onReset}
            className="inline-flex h-[38px] items-center gap-1.5 text-[13px] font-bold text-[#7a6f61] transition-colors hover:text-[#F97316] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#F97316]"
          >
            <X className="h-[15px] w-[15px]" />
            مسح الفلاتر ({activeCount})
          </button>
        </div>
      )}
    </div>
  );
}