import { Truck } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import { toMinor } from "@/cashier/api/money";
import { PAYMENT_LABEL, RECEIPT_LABEL, RETURN_STATUS_LABEL, SETTLEMENT_LABEL } from "@/cashier/api/purchasingAdapter";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";

const TONE = { unpaid: "text-amber-600", partial: "text-sky-700", paid: "text-emerald-700" };

// سجل تعاملات مورد واحد. الأرقام الأربعة الكبيرة جاية من حساب الخادم نفسه (من الفواتير والمدفوعات والمرتجعات)،
// مش بتتجمّع هنا من الفواتير: دفعة على الحساب أو مرتجع بدون فاتورة مش هيطلع في مجموع الفواتير.
export default function SupplierHistoryDialog({ open, onOpenChange, supplier, orders = [], returns = [], onPay }) {
  if (!supplier) return null;
  const mine = orders.filter((o) => o.supplierId === supplier.id && o.receipt !== "cancelled");
  const myReturns = returns.filter((r) => r.supplierId === supplier.id);
  const pieces = mine.filter((o) => o.receipt === "received").reduce((s, o) => s + o.pieces, 0);
  const owes = toMinor(supplier.balance) > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">سجل تعاملات {supplier.name}</DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-2">
            <span>{supplier.company}</span>
            <span className="num">{supplier.phone}</span>
            <span>{supplier.agent}</span>
          </DialogDescription>
        </DialogHeader>

        {mine.length === 0 && myReturns.length === 0 ? (
          <EmptyState icon={Truck} title="لا توجد فواتير توريد مسجلة" description="سجّل توريدًا جديدًا من صفحة المشتريات ليظهر هنا." compact />
        ) : (
          <>
            {mine.length > 0 && (
              <>
                <p className="text-xs font-bold text-muted-foreground">فواتير التوريد</p>
                <div className="max-h-[34vh] overflow-y-auto scroll-slim rounded-xl border border-border">
                  <table className="w-full min-w-[560px] text-sm">
                    <thead className="sticky top-0 bg-muted/70 backdrop-blur">
                      <tr className="text-xs text-muted-foreground">
                        <th className="px-3 py-2 text-start font-semibold">الفاتورة</th>
                        <th className="px-3 py-2 text-start font-semibold">التاريخ</th>
                        <th className="px-3 py-2 text-center font-semibold">القطع</th>
                        <th className="px-3 py-2 text-start font-semibold">الإجمالي</th>
                        <th className="px-3 py-2 text-start font-semibold">المتبقي</th>
                        <th className="px-3 py-2 text-center font-semibold">الاستلام</th>
                        <th className="px-3 py-2 text-center font-semibold">الدفع</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {mine.map((o) => (
                        <tr key={o.id}>
                          <td className="num px-3 py-2 font-medium">{o.number}</td>
                          <td className="num px-3 py-2 text-xs text-muted-foreground">{fmtDate(o.date)}</td>
                          <td className="num px-3 py-2 text-center">{fmtInt(o.pieces)}</td>
                          <td className="num px-3 py-2">{fmtMoney(o.total)}</td>
                          <td className={toMinor(o.balance) > 0 ? "num px-3 py-2 font-bold text-amber-600" : "num px-3 py-2 text-muted-foreground"}>{fmtMoney(o.balance)}</td>
                          <td className="px-3 py-2 text-center text-xs">{RECEIPT_LABEL[o.receipt]}</td>
                          <td className={`px-3 py-2 text-center text-xs font-semibold ${TONE[o.payment] ?? ""}`}>
                            {o.receipt === "received" ? PAYMENT_LABEL[o.payment] : "—"}
                            {o.receipt === "received" && toMinor(o.balance) > 0 && onPay && (
                              <Button variant="outline" className="ms-2 h-6 px-2 text-[11px]" onClick={() => onPay(supplier, o)}>دفع</Button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {myReturns.length > 0 && (
              <>
                <p className="text-xs font-bold text-muted-foreground">مرتجعات للمورد</p>
                <div className="max-h-[22vh] overflow-y-auto scroll-slim rounded-xl border border-border">
                  <table className="w-full min-w-[560px] text-sm">
                    <thead className="sticky top-0 bg-muted/70 backdrop-blur">
                      <tr className="text-xs text-muted-foreground">
                        <th className="px-3 py-2 text-start font-semibold">المرتجع</th>
                        <th className="px-3 py-2 text-start font-semibold">التاريخ</th>
                        <th className="px-3 py-2 text-center font-semibold">الكمية</th>
                        <th className="px-3 py-2 text-start font-semibold">القيمة</th>
                        <th className="px-3 py-2 text-center font-semibold">التسوية</th>
                        <th className="px-3 py-2 text-center font-semibold">الحالة</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {myReturns.map((r) => (
                        <tr key={r.id}>
                          <td className="num px-3 py-2 font-medium">{r.number}</td>
                          <td className="num px-3 py-2 text-xs text-muted-foreground">{fmtDate(r.date)}</td>
                          <td className="num px-3 py-2 text-center">{fmtInt(r.qty)}</td>
                          <td className={r.status === "accepted" ? "num px-3 py-2" : "num px-3 py-2 text-muted-foreground"}>{fmtMoney(r.amount)}</td>
                          <td className="px-3 py-2 text-center text-xs">{SETTLEMENT_LABEL[r.settlement]}</td>
                          <td className="px-3 py-2 text-center text-xs font-semibold">{RETURN_STATUS_LABEL[r.status]}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-[11px] text-muted-foreground">المرتجع ما بيتخصمش من الحساب إلا لما المورد يقبله.</p>
              </>
            )}
          </>
        )}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg bg-muted/50 px-3 py-2">
            <p className="text-[11px] text-muted-foreground">إجمالي التوريدات</p>
            <p className="num font-heading text-base font-bold">{fmtMoney(supplier.total)}</p>
          </div>
          <div className="rounded-lg bg-emerald-50 px-3 py-2">
            <p className="text-[11px] text-emerald-800">المدفوع</p>
            <p className="num font-heading text-base font-bold text-emerald-700">{fmtMoney(supplier.paid)}</p>
          </div>
          <div className="rounded-lg bg-sky-50 px-3 py-2">
            <p className="text-[11px] text-sky-800">مرتجعات مخصومة</p>
            <p className="num font-heading text-base font-bold text-sky-700">− {fmtMoney(supplier.credit)}</p>
          </div>
          <div className="rounded-lg bg-amber-50 px-3 py-2">
            <p className="text-[11px] text-amber-800">{owes ? "المستحق بعد المرتجعات" : "الرصيد"}</p>
            <p className="num font-heading text-base font-bold text-amber-700">{fmtMoney(supplier.balance)}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="num text-xs text-muted-foreground">
            {fmtInt(mine.length)} فاتورة • {fmtInt(pieces)} قطعة مستلمة • {fmtInt(myReturns.length)} مرتجعًا
          </p>
          {onPay && owes && <Button className="font-bold" onClick={() => onPay(supplier, null)}>تسجيل دفعة على الحساب</Button>}
        </div>
      </DialogContent>
    </Dialog>
  );
}
