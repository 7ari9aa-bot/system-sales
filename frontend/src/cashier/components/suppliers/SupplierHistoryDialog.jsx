import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import { supplierPurchases } from "@/cashier/lib/purchasesData";
import { supplierReturnCredit, supplierReturnsForSupplier } from "@/cashier/lib/storeOpsData";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";
import { Truck } from "lucide-react";

// سجل تعاملات مورد واحد: فواتير التوريد، مرتجعاته المخصومة من الحساب، والمستحق الصافي.
export default function SupplierHistoryDialog({ open, onOpenChange, supplier }) {
  if (!supplier) return null;
  const orders = supplierPurchases(supplier.id);
  const returns = supplierReturnsForSupplier(supplier.id);
  const totals = {
    total: orders.reduce((s, o) => s + o.total, 0),
    paid: orders.reduce((s, o) => s + o.paid, 0),
    balance: orders.reduce((s, o) => s + o.balance, 0),
    pieces: orders.reduce((s, o) => s + o.pieces, 0),
  };
  const credit = supplierReturnCredit(supplier.id);
  const net = +(totals.balance - credit).toFixed(2);

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

        {orders.length === 0 ? (
          <EmptyState icon={Truck} title="لا توجد فواتير توريد مسجلة" description="سجّل توريدًا جديدًا من صفحة المشتريات ليظهر هنا." compact />
        ) : (
          <>
            <p className="text-xs font-bold text-muted-foreground">فواتير التوريد</p>
            <div className="max-h-[38vh] overflow-y-auto scroll-slim rounded-xl border border-border">
              <table className="w-full min-w-[560px] text-sm">
                <thead className="sticky top-0 bg-muted/70 backdrop-blur">
                  <tr className="text-xs text-muted-foreground">
                    <th className="px-3 py-2 text-start font-semibold">الفاتورة</th>
                    <th className="px-3 py-2 text-start font-semibold">التاريخ</th>
                    <th className="px-3 py-2 text-center font-semibold">القطع</th>
                    <th className="px-3 py-2 text-start font-semibold">الإجمالي</th>
                    <th className="px-3 py-2 text-start font-semibold">المستحق</th>
                    <th className="px-3 py-2 text-center font-semibold">الحالة</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {orders.map((o) => (
                    <tr key={o.id}>
                      <td className="num px-3 py-2 font-medium">{o.number}</td>
                      <td className="num px-3 py-2 text-xs text-muted-foreground">{fmtDate(o.date)}</td>
                      <td className="num px-3 py-2 text-center">{fmtInt(o.pieces)}</td>
                      <td className="num px-3 py-2">{fmtMoney(o.total)}</td>
                      <td className={o.balance > 0 ? "num px-3 py-2 font-bold text-amber-600" : "num px-3 py-2 text-muted-foreground"}>
                        {fmtMoney(o.balance)}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <StatusBadge value={o.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {returns.length > 0 && (
              <>
                <p className="text-xs font-bold text-muted-foreground">مرتجعات للمورد</p>
                <div className="max-h-[26vh] overflow-y-auto scroll-slim rounded-xl border border-border">
                  <table className="w-full min-w-[560px] text-sm">
                    <thead className="sticky top-0 bg-muted/70 backdrop-blur">
                      <tr className="text-xs text-muted-foreground">
                        <th className="px-3 py-2 text-start font-semibold">المرتجع</th>
                        <th className="px-3 py-2 text-start font-semibold">التاريخ</th>
                        <th className="px-3 py-2 text-start font-semibold">الصنف</th>
                        <th className="px-3 py-2 text-center font-semibold">الكمية</th>
                        <th className="px-3 py-2 text-start font-semibold">القيمة</th>
                        <th className="px-3 py-2 text-center font-semibold">التسوية</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {returns.map((r) => (
                        <tr key={r.id}>
                          <td className="num px-3 py-2 font-medium">{r.number}</td>
                          <td className="num px-3 py-2 text-xs text-muted-foreground">{fmtDate(r.date)}</td>
                          <td className="px-3 py-2 text-xs">
                            {r.productName}
                            <span className="text-muted-foreground">
                              {" "}
                              ({r.color}/{r.size})
                            </span>
                          </td>
                          <td className="num px-3 py-2 text-center">{fmtInt(r.qty)}</td>
                          <td className="num px-3 py-2">{fmtMoney(r.amount)}</td>
                          <td className="px-3 py-2 text-center">
                            <StatusBadge kind="supplier_return" value={r.settlement} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg bg-muted/50 px-3 py-2">
                <p className="text-[11px] text-muted-foreground">إجمالي التوريدات</p>
                <p className="num font-heading text-base font-bold">{fmtMoney(totals.total)}</p>
              </div>
              <div className="rounded-lg bg-emerald-50 px-3 py-2">
                <p className="text-[11px] text-emerald-800">المدفوع</p>
                <p className="num font-heading text-base font-bold text-emerald-700">{fmtMoney(totals.paid)}</p>
              </div>
              <div className="rounded-lg bg-sky-50 px-3 py-2">
                <p className="text-[11px] text-sky-800">مرتجعات مخصومة</p>
                <p className="num font-heading text-base font-bold text-sky-700">− {fmtMoney(credit)}</p>
              </div>
              <div className="rounded-lg bg-amber-50 px-3 py-2">
                <p className="text-[11px] text-amber-800">المستحق بعد المرتجعات</p>
                <p className="num font-heading text-base font-bold text-amber-700">{fmtMoney(net)}</p>
              </div>
            </div>
            <p className="num text-xs text-muted-foreground">
              {fmtInt(orders.length)} فاتورة توريد • {fmtInt(totals.pieces)} قطعة • {fmtInt(returns.length)} مرتجعًا
            </p>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}