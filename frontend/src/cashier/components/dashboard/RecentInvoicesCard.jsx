import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { invoices } from "@/cashier/lib/mockData";
import { fmtMoney, fmtInt, fmtTime } from "@/cashier/lib/format";

// أحدث فواتير البيع اليوم.
export default function RecentInvoicesCard() {
  const rows = invoices.slice(0, 6);

  return (
    <SectionCard
      title="أحدث فواتير البيع"
      description="آخر العمليات المسجلة على الكاشير"
      noPadding
      action={
        <Button asChild variant="ghost" size="sm" className="h-7 gap-1 text-xs text-primary hover:text-primary">
          <Link to="/cashier/sales">
            كل الفواتير
            <ArrowLeft className="h-3.5 w-3.5" />
          </Link>
        </Button>
      }
    >
      <div className="overflow-x-auto scroll-slim">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="bg-muted/50 text-xs text-muted-foreground">
              <th className="px-4 py-2 text-start font-semibold">رقم الفاتورة</th>
              <th className="px-4 py-2 text-start font-semibold">الوقت</th>
              <th className="px-4 py-2 text-start font-semibold">العميل</th>
              <th className="px-4 py-2 text-start font-semibold">القطع</th>
              <th className="px-4 py-2 text-start font-semibold">الإجمالي</th>
              <th className="px-4 py-2 text-start font-semibold">الحالة</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((inv) => (
              <tr key={inv.id} className="transition-colors hover:bg-accent/40">
                <td className="px-4 py-2.5">
                  <Link to="/cashier/sales/$invoiceId" params={{ invoiceId: inv.id }} className="num font-semibold text-primary hover:underline">
                    {inv.number}
                  </Link>
                </td>
                <td className="num px-4 py-2.5 text-xs text-muted-foreground">{fmtTime(inv.date)}</td>
                <td className="px-4 py-2.5">{inv.customerName}</td>
                <td className="num px-4 py-2.5">{fmtInt(inv.pieces)}</td>
                <td className="num px-4 py-2.5 font-semibold">{fmtMoney(inv.total)}</td>
                <td className="px-4 py-2.5">
                  <StatusBadge kind="invoice" value={inv.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}