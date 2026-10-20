import { Ban, CircleCheck, Printer, Repeat2, Undo2 } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import { fmtDateTime, fmtMoney, PAYMENT_METHODS } from "@/cashier/lib/format";

const ICONS = {
  create: CircleCheck,
  print: Printer,
  return: Undo2,
  exchange: Repeat2,
  cancel: Ban,
};

// سجل العمليات المرتبطة بالفاتورة (إنشاء، مرتجع) من واقع إيصالات الخادم فقط.
export default function OperationsLogDialog({ open, onOpenChange, invoice }) {
  if (!invoice) return null;

  // Only events the backend really recorded: the sale itself and each return receipt issued against it.
  // (No "printed" event: reprints are not stored, so showing one would be invented.)
  const payment = invoice.paymentLabel || PAYMENT_METHODS[invoice.payment]?.label || "";
  const who = invoice.cashier ? `بواسطة ${invoice.cashier} • ` : "";
  const events = [
    {
      id: "ev-1",
      kind: "create",
      title: "تم إنشاء الفاتورة",
      detail: `${who}${payment} • ${fmtMoney(invoice.total)}`,
      time: invoice.date,
    },
    ...(invoice.returns ?? []).map((r, i) => ({
      id: `ev-r-${i}`,
      kind: "return",
      title: "عملية استرجاع",
      detail: `${r.number} • ${fmtMoney(r.amount)}`,
      time: r.date,
    })),
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">
            سجل العمليات — <span className="num">{invoice.number}</span>
          </DialogTitle>
          <DialogDescription>الإنشاء والمرتجعات المسجّلة على هذه الفاتورة.</DialogDescription>
        </DialogHeader>

        {events.length === 0 ? (
          <EmptyState title="لا توجد عمليات مسجلة" compact />
        ) : (
          <ol className="relative space-y-4 ps-5">
            <span className="absolute bottom-2 right-[7px] top-2 w-px bg-border" aria-hidden="true" />
            {events.map((ev) => {
              const Icon = ICONS[ev.kind] ?? CircleCheck;
              return (
                <li key={ev.id} className="relative">
                  <span className="absolute -right-5 top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-card ring-1 ring-border">
                    <Icon className="h-2.5 w-2.5 text-primary" />
                  </span>
                  <p className="text-sm font-semibold">{ev.title}</p>
                  <p className="text-xs text-muted-foreground">{ev.detail}</p>
                  <p className="num text-[11px] text-muted-foreground/80">{fmtDateTime(ev.time)}</p>
                </li>
              );
            })}
          </ol>
        )}
      </DialogContent>
    </Dialog>
  );
}