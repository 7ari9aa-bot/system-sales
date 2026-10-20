import { Banknote, CreditCard, Wallet } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

const METHODS = [
  { key: "cash", label: "نقدي", icon: Banknote, hint: "خصم فوري من درج الكاشير" },
  { key: "card", label: "بطاقة", icon: CreditCard, hint: "فيزا / ماستركارد" },
  { key: "wallet", label: "محفظة إلكترونية", icon: Wallet, hint: "فودافون كاش / إنستاپاي" },
  { key: "credit", label: "آجل", icon: Wallet, hint: "يُسجَّل على حساب العميل" },
];

// نافذة اختيار طريقة الدفع وإتمام البيع.
export default function PaymentDialog({ open, onOpenChange, total, method, onMethodChange, paid, onPaidChange, onConfirm, customerName, enabledMethods }) {
  const activeMethod = method;
  const remaining = paid - total;
  const isCredit = activeMethod === "credit";
  // الطرق المعطّلة من الإعدادات لا تظهر للكاشير.
  const methods = enabledMethods ? METHODS.filter((m) => enabledMethods.includes(m.key)) : METHODS;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">إتمام عملية البيع</DialogTitle>
          <DialogDescription>
            العميل: {customerName} • الإجمالي المستحق {fmtMoney(total)}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">طريقة الدفع</p>
            <div className="grid grid-cols-2 gap-2">
              {methods.map((m) => {
                const disabled = m.key === "credit" && customerName === "عميل نقدي";
                return (
                  <button
                    key={m.key}
                    type="button"
                    disabled={disabled}
                    onClick={() => onMethodChange(m.key)}
                    className={cn(
                      "flex items-start gap-2.5 rounded-xl border p-3 text-start transition-colors",
                      activeMethod === m.key ? "border-primary bg-accent" : "border-border hover:bg-muted/50",
                      disabled && "cursor-not-allowed opacity-50",
                    )}
                  >
                    <m.icon className={cn("mt-0.5 h-4 w-4", activeMethod === m.key ? "text-primary" : "text-muted-foreground")} />
                    <span>
                      <span className="block text-sm font-semibold">{m.label}</span>
                      <span className="block text-[11px] text-muted-foreground">
                        {disabled ? "يتطلب اختيار عميل مسجل" : m.hint}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground" htmlFor="pay-amount">
                المبلغ المستلم
              </label>
              <Input
                id="pay-amount"
                type="number"
                min={0}
                value={paid}
                onChange={(e) => onPaidChange(Number(e.target.value))}
                className="num h-8 font-bold"
              />
            </div>
            <div className="space-y-1.5">
              <p className="text-xs font-semibold text-muted-foreground">{remaining < 0 ? "المتبقي على العميل" : "الباقي للعميل"}</p>
              <p className={cn("num flex h-8 items-center font-heading text-[13px] font-bold", remaining < 0 ? "text-amber-600" : "text-emerald-600")}>
                {fmtMoney(Math.abs(remaining))}
              </p>
            </div>
          </div>

          {isCredit && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              سيُسجَّل المبلغ غير المدفوع على حساب العميل {customerName} ويظهر في كشف الحساب.
            </p>
          )}

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => onOpenChange(false)}>
              رجوع للفاتورة
            </Button>
            <Button className="h-9 flex-1 font-bold" onClick={onConfirm}>
              تأكيد البيع وطباعة الفاتورة
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}