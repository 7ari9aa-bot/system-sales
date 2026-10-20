import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";

const FIELD = "num h-8 w-[84px] text-center font-bold";

// خصم الفاتورة: نسبة مئوية أو مبلغ ثابت بالجنيه.
export default function PosInvoiceDiscounts({
  pct,
  onPctChange,
  amount,
  onAmountChange,
  maxDiscount = 100,
  disabled = false,
}) {
  return (
    <div className="flex shrink-0 flex-col gap-1 rounded-lg border border-border bg-card px-3 py-1.5">
      <span className="text-[11px] font-semibold text-muted-foreground">خصم الفاتورة</span>

      <div className="flex items-start gap-3">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor="invoice-discount-pct" className="text-[11px] font-medium text-muted-foreground">
            خصم %
          </Label>
          <Input
            id="invoice-discount-pct"
            type="number"
            min={0}
            max={maxDiscount}
            value={pct}
            disabled={disabled}
            onChange={(e) => onPctChange(e.target.value)}
            className={FIELD}
          />
        </div>

        <div className="flex flex-col gap-0.5">
          <Label htmlFor="invoice-discount-amount" className="text-[11px] font-medium text-muted-foreground">
            خصم عادي (ج.م.)
          </Label>
          <Input
            id="invoice-discount-amount"
            type="number"
            min={0}
            value={amount}
            disabled={disabled}
            onChange={(e) => onAmountChange(e.target.value)}
            className={FIELD}
          />
        </div>
      </div>
    </div>
  );
}