import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowRight, History, Printer, Repeat2, SearchX, Undo2, User, Wallet } from "lucide-react";
import { useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import PageHeader from "@/cashier/components/ui-kit/PageHeader";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import OperationsLogDialog from "@/cashier/components/sales/OperationsLogDialog";
import ReceiptDialog from "@/cashier/components/pos/ReceiptDialog";
import { useAuth } from "@/lib/AuthContext";
import { useInvoice } from "@/cashier/api/usePosSale";
import { useShifts } from "@/cashier/api/useShifts";
import { fmtDateTime, fmtInt, fmtMoney, PAYMENT_METHODS } from "@/cashier/lib/format";


export default function InvoiceDetailPage() {
  const { invoiceId } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const sessionId = params.get("shift") ?? "";
  const { user } = useAuth();
  const me = user?.id ? { [user.id]: user.full_name || user.email } : {};
  const shifts = useShifts({ employees: me }).data ?? [];
  const cashierOfShift = shifts.find((x) => x.id === sessionId)?.employeeId === user?.id ? (user?.full_name || user?.email || "") : "";
  const { data: invoice, isLoading, isError } = useInvoice(invoiceId, sessionId, { cashier: cashierOfShift });
  const [logOpen, setLogOpen] = useState(false);
  const [receipt, setReceipt] = useState(null);

  if (isLoading) return <div role="status" className="p-8 text-center text-sm text-muted-foreground">جارٍ تحميل الفاتورة…</div>;

  if (!invoice) {
    return (
      <div className="animate-fade-up">
        <PageHeader title="تفاصيل الفاتورة" />
        <SectionCard>
          <EmptyState
            icon={SearchX}
            title="لم يتم العثور على الفاتورة"
            description={isError ? "تعذّر تحميل الفاتورة. تأكد من الاتصال ثم أعد المحاولة من سجل المبيعات." : "الفاتورة غير موجودة. عد إلى سجل المبيعات واختر فاتورة من القائمة."}
            action={
              <Button asChild variant="outline">
                <Link to="/cashier/sales">العودة إلى سجل المبيعات</Link>
              </Button>
            }
          />
        </SectionCard>
      </div>
    );
  }

  const remaining = invoice.remaining;
  const returnedAmount = invoice.returnedAmount;

  return (
    <div className="animate-fade-up">
      <PageHeader title={`تفاصيل الفاتورة ${invoice.number}`} description={fmtDateTime(invoice.date)}>
        <Button variant="ghost" className="gap-2 text-muted-foreground" onClick={() => navigate("/cashier/sales")}>
          <ArrowRight className="h-4 w-4" />
          رجوع للسجل
        </Button>
        <Button variant="outline" className="gap-2" onClick={() => setLogOpen(true)}>
          <History className="h-4 w-4" />
          سجل العمليات
        </Button>
        <Button variant="outline" className="gap-2" onClick={() => setReceipt(invoice)}>
          <Printer className="h-4 w-4" />
          طباعة الفاتورة
        </Button>
        <Button asChild className="gap-2">
          <Link to={`/cashier/returns?invoice=${encodeURIComponent(invoice.number)}`}>
            <Repeat2 className="h-4 w-4" />
            استرجاع / استبدال
          </Link>
        </Button>
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-12">
        <div className="lg:col-span-4 space-y-4">
          <SectionCard title="بيانات الفاتورة">
            <dl className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">رقم الفاتورة</dt>
                <dd className="num font-bold">{invoice.number}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">التاريخ والوقت</dt>
                <dd className="num">{fmtDateTime(invoice.date)}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">الحالة</dt>
                <dd>
                  <StatusBadge kind="invoice" value={invoice.status} />
                </dd>
              </div>
            </dl>
          </SectionCard>

          <SectionCard title="العميل والموظف">
            <ul className="space-y-3 text-sm">
              <li className="flex items-start gap-2">
                <User className="mt-0.5 h-4 w-4 text-muted-foreground" />
                <span>
                  <span className="block font-semibold">{invoice.customerName}</span>
                </span>
              </li>
              <li className="flex items-start gap-2">
                <User className="mt-0.5 h-4 w-4 text-muted-foreground" />
                <span>
                  <span className="block font-semibold">{invoice.cashier || "غير معروف"}</span>
                  <span className="block text-xs text-muted-foreground">الكاشير المسؤول عن البيع</span>
                </span>
              </li>
              <li className="flex items-start gap-2">
                <Wallet className="mt-0.5 h-4 w-4 text-muted-foreground" />
                <span>
                  <span className="flex items-center gap-2">
                    <span className="font-semibold">{invoice.paymentLabel}</span>
                  </span>
                  <span className="num block text-xs text-muted-foreground">المدفوع {fmtMoney(invoice.total - remaining)}</span>
                </span>
              </li>
            </ul>
          </SectionCard>

          <SectionCard title="ملخص المبالغ">
            <ul className="space-y-2.5 text-sm">
              <li className="flex items-center justify-between">
                <span className="text-muted-foreground">عدد القطع</span>
                <span className="num font-semibold">{fmtInt(invoice.pieces)}</span>
              </li>
              <li className="flex items-center justify-between">
                <span className="text-muted-foreground">الإجمالي قبل الخصم</span>
                <span className="num">{fmtMoney(invoice.subTotal)}</span>
              </li>
              <li className="flex items-center justify-between">
                <span className="text-muted-foreground">الخصومات</span>
                <span className="num text-rose-600">- {fmtMoney(invoice.discount)}</span>
              </li>
              <li className="flex items-center justify-between border-t border-border pt-2.5">
                <span className="font-heading font-bold">الإجمالي النهائي</span>
                <span className="num font-heading text-base font-extrabold text-primary">{fmtMoney(invoice.total)}</span>
              </li>
              <li className="flex items-center justify-between">
                <span className="text-muted-foreground">المبلغ المتبقي</span>
                <span className={`num font-semibold ${remaining > 0 ? "text-amber-600" : "text-emerald-600"}`}>{fmtMoney(remaining)}</span>
              </li>
              {returnedAmount > 0 && (
                <li className="flex items-center justify-between">
                  <span className="text-muted-foreground">قيمة المرتجعات المرتبطة</span>
                  <span className="num font-semibold text-rose-600">{fmtMoney(returnedAmount)}</span>
                </li>
              )}
            </ul>
          </SectionCard>
        </div>

        <div className="min-w-0 lg:col-span-8 space-y-4">
          <SectionCard title="الأصناف المباعة" description={`${invoice.items.length} صنفًا • ${fmtInt(invoice.pieces)} قطعة`} noPadding>
            <div className="overflow-x-auto scroll-slim">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="bg-muted/50 text-xs text-muted-foreground">
                    <th className="px-4 py-2 text-start font-semibold">الكود</th>
                    <th className="px-4 py-2 text-start font-semibold">المنتج</th>
                    <th className="px-4 py-2 text-center font-semibold">الكمية</th>
                    <th className="px-4 py-2 text-start font-semibold">سعر الوحدة</th>
                    <th className="px-4 py-2 text-center font-semibold">مرتجع</th>
                    <th className="px-4 py-2 text-start font-semibold">الإجمالي</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {invoice.items.map((it, i) => (
                    <tr key={`${it.code}-${i}`} className="transition-colors hover:bg-accent/30">
                      <td className="num px-4 py-2.5 text-xs text-muted-foreground">{it.code}</td>
                      <td className="px-4 py-2.5 font-medium">{it.name}</td>
                      <td className="num px-4 py-2.5 text-center">{it.qty}</td>
                      <td className="num px-4 py-2.5">{fmtMoney(it.price)}</td>
                      <td className="num px-4 py-2.5 text-center text-rose-600">{it.returnedQty > 0 ? it.returnedQty : "—"}</td>
                      <td className="num px-4 py-2.5 font-bold">{fmtMoney(it.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard
            title="عمليات الاسترجاع والاستبدال المرتبطة"
            description="مرتبطة بفاتورة البيع الأصلية ولا تُخلط معها"
            action={
              <Button asChild size="sm" variant="outline" className="gap-1.5">
                <Link to={`/cashier/returns?invoice=${encodeURIComponent(invoice.number)}`}>
                  <Undo2 className="h-3.5 w-3.5" />
                  تسجيل عملية جديدة
                </Link>
              </Button>
            }
          >
            {invoice.returns.length === 0 ? (
              <EmptyState
                icon={Undo2}
                title="لا توجد مرتجعات على هذه الفاتورة"
                description="العملية الأصلية مسجلة كبيع فقط. عند الاسترجاع أو الاستبدال ستظهر هنا بحالة مستقلة."
                compact
              />
            ) : (
              <ul className="space-y-3">
                {invoice.returns.map((r) => (
                  <li key={r.id} className="rounded-xl border border-border p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="num text-xs font-semibold">{r.number}</span>
                        <span className="num text-xs text-muted-foreground">{fmtDateTime(r.date)}</span>
                      </div>
                      <span className="num font-heading text-base font-bold text-rose-600">{fmtMoney(r.amount)}</span>
                    </div>
                    <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                      {r.items.map((ri, i) => (
                        <li key={`${ri.name}-${i}`}>
                          {ri.name} • كمية {ri.qty}
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        </div>
      </div>

      <OperationsLogDialog open={logOpen} onOpenChange={setLogOpen} invoice={invoice} />
      <ReceiptDialog open={!!receipt} onOpenChange={(o) => !o && setReceipt(null)} receipt={receipt} />
    </div>
  );
}