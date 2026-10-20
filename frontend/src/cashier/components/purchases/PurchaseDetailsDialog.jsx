import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { toMinor } from "@/cashier/api/money";
import { PAYMENT_LABEL, RECEIPT_LABEL } from "@/cashier/api/purchasingAdapter";
import { colorHex } from "@/cashier/lib/mockData";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";

// تفاصيل فاتورة توريد: البنود والتكاليف، حالة الاستلام وحالة الدفع منفصلتين، وإجراءاتها.
export default function PurchaseDetailsDialog({ open, onOpenChange, order, onPay, onReceive, onCancel, busy, error }) {
  if (!order) return null;
  const canPay = order.receipt === "received" && toMinor(order.balance) > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">فاتورة توريد {order.number}</DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-2">
            <span>{order.supplierName}</span>
            <span className="num">{fmtDate(order.date)}</span>
            <span className="font-semibold">{RECEIPT_LABEL[order.receipt]}</span>
            {order.receipt === "received" && <span className="font-semibold">• {PAYMENT_LABEL[order.payment]}</span>}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[50vh] overflow-y-auto scroll-slim rounded-xl border border-border">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="sticky top-0 bg-muted/70 backdrop-blur">
              <tr className="text-xs text-muted-foreground">
                <th className="px-3 py-2 text-start font-semibold">الصنف</th>
                <th className="px-3 py-2 text-center font-semibold">الكمية</th>
                <th className="px-3 py-2 text-start font-semibold">تكلفة الوحدة</th>
                <th className="px-3 py-2 text-start font-semibold">الإجمالي</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {order.items.map((it, index) => (
                <tr key={`${it.variantId}-${index}`}>
                  <td className="px-3 py-2">
                    <span className="block font-medium">{it.name}</span>
                    {(it.color || it.size) && (
                      <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
                        {it.color && <ColorSwatch color={it.color} hex={colorHex(it.color)} showLabel={false} />}
                        {it.size && <>مقاس {it.size}</>}
                      </span>
                    )}
                  </td>
                  <td className="num px-3 py-2 text-center">{fmtInt(it.qty)}</td>
                  <td className="num px-3 py-2">{fmtMoney(it.unitCost)}</td>
                  <td className="num px-3 py-2 font-semibold">{fmtMoney(it.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg bg-muted/50 px-3 py-2">
            <p className="text-[11px] text-muted-foreground">إجمالي الفاتورة</p>
            <p className="num font-heading text-base font-bold">{fmtMoney(order.total)}</p>
          </div>
          <div className="rounded-lg bg-emerald-50 px-3 py-2">
            <p className="text-[11px] text-emerald-800">المدفوع</p>
            <p className="num font-heading text-base font-bold text-emerald-700">{fmtMoney(order.paid)}</p>
          </div>
          <div className="rounded-lg bg-amber-50 px-3 py-2">
            <p className="text-[11px] text-amber-800">المتبقي</p>
            <p className="num font-heading text-base font-bold text-amber-700">{fmtMoney(order.balance)}</p>
          </div>
        </div>

        {order.note && <p className="rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground">{order.note}</p>}
        {error && <p role="alert" className="rounded-md border border-[#F1C7C3] bg-[#FDECEA] px-3 py-2 text-xs font-semibold text-[#B3261E]">{error}</p>}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="num text-xs text-muted-foreground">{fmtInt(order.pieces)} قطعة</p>
          <div className="flex gap-2">
            {order.receipt === "draft" && (
              <>
                <Button variant="outline" disabled={busy} onClick={() => onCancel(order)}>إلغاء الفاتورة</Button>
                <Button className="font-bold" disabled={busy} onClick={() => onReceive(order)}>استلام البضاعة</Button>
              </>
            )}
            {canPay && <Button className="font-bold" disabled={busy} onClick={() => onPay(order)}>تسجيل دفعة</Button>}
          </div>
        </div>
        {order.receipt === "received" && <p className="text-[11px] text-muted-foreground">الفاتورة المستلمة ما بتتلغيش: لو فيه بضاعة هترجع للمورد، سجّل مرتجع مورد.</p>}
      </DialogContent>
    </Dialog>
  );
}
