import { History } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { colorHex, stockMovements } from "@/cashier/lib/mockData";
import { fmtDateTime, fmtInt } from "@/cashier/lib/format";

// حركات متغير واحد (لون / مقاس) مع الرصيد بعد كل حركة.
export default function VariantMovementsDialog({ open, onOpenChange, variant }) {
  if (!variant) return null;
  const rows = stockMovements.filter((m) => m.sku === variant.sku);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{variant.productName}</DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-2">
            <ColorSwatch color={variant.color} hex={colorHex(variant.color)} />
            <span>مقاس {variant.size}</span>
            <span className="num">{variant.sku}</span>
            <span className="num">الرصيد الحالي {fmtInt(variant.stock)}</span>
          </DialogDescription>
        </DialogHeader>

        {rows.length === 0 ? (
          <EmptyState icon={History} title="لا توجد حركات مسجلة" description="لم تُسجَّل أي حركة على هذا المتغير حتى الآن." compact />
        ) : (
          <div className="max-h-[55vh] overflow-y-auto scroll-slim rounded-xl border border-border">
            <table className="w-full min-w-[520px] text-sm">
              <thead className="sticky top-0 bg-muted/70 backdrop-blur">
                <tr className="text-xs text-muted-foreground">
                  <th className="px-3 py-2 text-start font-semibold">التاريخ</th>
                  <th className="px-3 py-2 text-start font-semibold">نوع الحركة</th>
                  <th className="px-3 py-2 text-center font-semibold">داخل</th>
                  <th className="px-3 py-2 text-center font-semibold">خارج</th>
                  <th className="px-3 py-2 text-center font-semibold">الرصيد</th>
                  <th className="px-3 py-2 text-start font-semibold">المستند</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((m) => (
                  <tr key={m.id}>
                    <td className="num px-3 py-2 text-xs text-muted-foreground">{fmtDateTime(m.date)}</td>
                    <td className="px-3 py-2">
                      <StatusBadge kind="movement" value={m.type} />
                    </td>
                    <td className="num px-3 py-2 text-center text-emerald-600">{m.qtyIn || "—"}</td>
                    <td className="num px-3 py-2 text-center text-rose-600">{m.qtyOut || "—"}</td>
                    <td className="num px-3 py-2 text-center font-bold">{m.balance}</td>
                    <td className="num px-3 py-2 text-xs">{m.doc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}