import { Pencil, Printer, Plus } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { fmtMoney } from "@/cashier/lib/format";
import { shop } from "@/cashier/lib/mockData";
import FlipButtons from "@/cashier/components/pos/FlipButtons";

// معاينة الفاتورة الحرارية ٨٠ مم قبل الطباعة.
export default function ReceiptDialog({ open, onOpenChange, receipt, onNewSale, onEdit, onPrev, onNext, prevDisabled, nextDisabled }) {
  if (!receipt) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">معاينة الفاتورة</DialogTitle>
        </DialogHeader>

        <div className="max-h-[60vh] overflow-y-auto scroll-slim rounded-xl border border-dashed border-border bg-muted/30 p-3">
          <div className="print-area mx-auto w-full max-w-[320px] rounded-lg bg-white p-4 font-body text-[12px] leading-relaxed text-black shadow-sm">
            <div className="text-center">
              <p className="font-heading text-base font-extrabold">{shop.name}</p>
              <p>{shop.branch}</p>
              <p className="num">{shop.phone}</p>
              <p className="num">الرقم الضريبي: {shop.taxId}</p>
            </div>
            <div className="my-3 border-t border-dashed border-black/40" />
            <div className="flex justify-between">
              <span>فاتورة رقم</span>
              <span className="num font-bold">{receipt.number}</span>
            </div>
            <div className="flex justify-between">
              <span>التاريخ</span>
              <span className="num">{new Date(receipt.date).toLocaleString("ar-EG", { dateStyle: "short", timeStyle: "short" })}</span>
            </div>
            <div className="flex justify-between">
              <span>الكاشير</span>
              <span>{receipt.cashier}</span>
            </div>
            <div className="flex justify-between">
              <span>العميل</span>
              <span>{receipt.customerName}</span>
            </div>
            <div className="my-3 border-t border-dashed border-black/40" />
            <table className="w-full">
              <thead>
                <tr className="border-b border-black/30 text-[11px]">
                  <th className="py-1 text-start">الصنف</th>
                  <th className="py-1 text-center">كمية</th>
                  <th className="py-1 text-start">إجمالي</th>
                </tr>
              </thead>
              <tbody>
                {receipt.items.map((it, i) => (
                  <tr key={`${it.code}-${i}`} className="border-b border-dotted border-black/20">
                    <td className="py-1">
                      <span className="block">{it.name}</span>
                      <span className="block text-[10px] text-black/60">
                        {it.color} / {it.size}
                      </span>
                    </td>
                    <td className="num py-1 text-center">{it.qty}</td>
                    <td className="num py-1 text-start">{it.total.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="my-3 border-t border-dashed border-black/40" />
            <div className="space-y-1">
              <div className="flex justify-between">
                <span>عدد القطع</span>
                <span className="num">{receipt.pieces}</span>
              </div>
              <div className="flex justify-between">
                <span>الإجمالي قبل الخصم</span>
                <span className="num">{receipt.subTotal.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span>خصم الأصناف</span>
                <span className="num">{(receipt.lineDiscount ?? receipt.discount ?? 0).toFixed(2)}</span>
              </div>
              {receipt.invoiceDiscount > 0 && (
                <div className="flex justify-between">
                  <span>خصم الفاتورة</span>
                  <span className="num">{receipt.invoiceDiscount.toFixed(2)}</span>
                </div>
              )}
              <div className="flex justify-between border-t border-black/40 pt-1 font-bold">
                <span>الإجمالي النهائي</span>
                <span className="num">{receipt.total.toFixed(2)} ج.م</span>
              </div>
              <div className="flex justify-between">
                <span>المدفوع ({receipt.paymentLabel})</span>
                <span className="num">{receipt.paid.toFixed(2)}</span>
              </div>
            </div>
            {receipt.note && (
              <p className="mt-2 border-t border-dashed border-black/40 pt-2 text-[11px]">ملاحظة: {receipt.note}</p>
            )}
            <div className="my-3 border-t border-dashed border-black/40" />
            <p className="text-center text-[11px]">
              شكرًا لتعاملكم معنا • الاستبدال خلال ١٤ يومًا بشرط وجود الفاتورة
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3">
          <StatusBadge kind="invoice" value={receipt.status} />
          <span className="num text-xs text-muted-foreground">الإجمالي {fmtMoney(receipt.total)}</span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {onPrev && (
            <FlipButtons onPrev={onPrev} onNext={onNext} prevDisabled={prevDisabled} nextDisabled={nextDisabled} />
          )}
          <Button variant="outline" className="flex-1 gap-2" onClick={() => window.print()}>
            <Printer className="h-4 w-4" />
            طباعة
          </Button>
          {onEdit && (
            <Button variant="outline" className="flex-1 gap-2" onClick={onEdit}>
              <Pencil className="h-4 w-4" />
              تعديل
            </Button>
          )}
          <Button
            className="flex-1 gap-2 font-bold"
            onClick={() => {
              onOpenChange(false);
              onNewSale?.();
            }}
          >
            <Plus className="h-4 w-4" />
            فاتورة جديدة
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}