import { useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Textarea } from "@/cashier/components/ui/textarea";
import { fmtMoney } from "@/cashier/lib/format";

/**
 * إلغاء فاتورة معتمدة (Void).
 *
 * الإلغاء مش مرتجع: المرتجع معناه «العميل رجّع البضاعة»، والإلغاء معناه «البيعة دي ما كانش
 * المفروض تحصل» (مقاس غلط، سعر غلط، لون غلط). عشان كده الخادم بيعمل مستند عكسي POS-VOID،
 * بيرجّع البضاعة للمخزون بتكلفتها، بيرد الفلوس على وسائل الدفع الأصلية، وبيستبعد الفاتورة من
 * تقارير المبيعات والأرباح. المستند الأصلي ما بيتحذفش أبدًا.
 *
 * السبب مطلوب، والصلاحية (pos:override) بيتحقق منها الخادم: لو الفاتورة على وردية كاشير تاني
 * واللي بيلغي مش مدير، الخادم بيرفض والرسالة بتظهر هنا زي ما هي.
 */
export default function VoidInvoiceDialog({ open, onOpenChange, invoice, pending = false, error = null, onConfirm }) {
  const [reason, setReason] = useState("");
  if (!invoice) return null;

  const ready = reason.trim().length > 0 && !pending;
  const partlyReturned = Number(invoice.returnedQty ?? invoice.returnedUnits ?? 0) > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">إلغاء الفاتورة {invoice.number}</DialogTitle>
          <DialogDescription>
            الإلغاء بيعكس البيعة بالكامل: البضاعة ترجع للمخزون، والفلوس ترد على وسائل الدفع الأصلية،
            والفاتورة تخرج من تقارير المبيعات والأرباح. الفاتورة الأصلية بتفضل محفوظة ومش بتتحذف.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="num flex items-center justify-between rounded-xl border border-border bg-muted/40 px-3 py-2 text-xs">
            <span className="text-muted-foreground">قيمة الفاتورة</span>
            <span className="font-bold">{fmtMoney(Number(invoice.total ?? 0))}</span>
          </div>
          {partlyReturned ? (
            <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700">
              جزء من الفاتورة دي رجع بالفعل كمرتجع. الخادم بيرفض الإلغاء في الحالة دي: كمّل الباقي كمرتجع.
            </p>
          ) : null}
          <label className="grid gap-1">
            <span className="text-xs font-semibold">سبب الإلغاء (مطلوب)</span>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              maxLength={255}
              placeholder="مثال: المقاس اتسجل غلط والعميل خد مقاس تاني"
              aria-label="سبب الإلغاء"
            />
          </label>
          {error ? (
            <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            رجوع
          </Button>
          <Button
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={!ready || partlyReturned}
            onClick={() => onConfirm({ orderId: invoice.orderId ?? invoice.id, reason: reason.trim() })}
          >
            {pending ? "جارٍ الإلغاء…" : "تأكيد الإلغاء"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
