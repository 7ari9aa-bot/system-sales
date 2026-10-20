import { fmtNumber } from "@/cashier/lib/format";

// ملخص الفاتورة: أعمدة موحّدة حتى تتراصف الأرقام أسفل بعضها.
export default function PosInvoiceSummary({ subTotal = 0, discount = 0, total = 0 }) {
  return (
    <div className="w-[290px] shrink-0 rounded-lg border border-border bg-card px-3 py-1.5 text-[13px]">
      <div className="grid grid-cols-[1fr_auto] items-center gap-x-5 gap-y-0.5">
        <span className="text-muted-foreground">المجموع قبل الخصم</span>
        <span className="num text-end font-semibold">{fmtNumber(subTotal)} ج.م</span>

        <span className="text-muted-foreground">إجمالي الخصم</span>
        <span className="num text-end font-semibold">{discount > 0 ? "-" : ""}{fmtNumber(discount)} ج.م</span>

        <span className="col-span-2 border-t border-border" />

        <span className="font-bold">المطلوب دفعه</span>
        <span className="num text-end text-[16px] font-bold text-primary">{fmtNumber(total)} ج.م</span>
      </div>
    </div>
  );
}