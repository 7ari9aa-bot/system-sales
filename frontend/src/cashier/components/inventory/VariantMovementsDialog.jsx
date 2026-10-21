import { History } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { colorHex } from "@/cashier/lib/uiConstants";
import { useVariantMovements } from "@/cashier/api/useMovements";
import { fmtDateTime, fmtInt } from "@/cashier/lib/format";

const DOC_LABEL = { order: "فاتورة", purchase_order: "فاتورة شراء", supplier_return: "مرتجع مورد" };

// What the movement hangs off. A manual adjustment names no document, so say so instead of a dash.
function docLabel(m) {
  if (m.docType) return DOC_LABEL[m.docType] ?? m.docType;
  return m.reason === "adjustment" ? "تسوية يدوية" : null;
}

// حركات متغير واحد (لون / مقاس) مع الرصيد بعد كل حركة.
export default function VariantMovementsDialog({ open, onOpenChange, variant }) {
  const ledger = useVariantMovements(open ? variant?.id : null);
  if (!variant) return null;
  // Reservation hold/release rows are availability bookkeeping, not goods moving: keep them out of
  // the in/out table so the running balance reads cleanly.
  const rows = (ledger.data ?? []).filter((m) => !m.availabilityOnly);

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

        {ledger.isError ? (
          <div role="alert" className="p-6 text-center text-sm">
            <p className="font-medium">تعذّر تحميل الحركات</p>
            <button type="button" className="mt-2 text-xs underline" onClick={() => ledger.refetch()}>
              إعادة المحاولة
            </button>
          </div>
        ) : ledger.isPending ? (
          <p className="py-8 text-center text-sm text-muted-foreground">جاري تحميل الحركات…</p>
        ) : rows.length === 0 ? (
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
                      <StatusBadge kind="movement" value={m.reason} />
                    </td>
                    <td className="num px-3 py-2 text-center text-emerald-600">{m.qtyIn || "—"}</td>
                    <td className="num px-3 py-2 text-center text-rose-600">{m.qtyOut || "—"}</td>
                    <td className="num px-3 py-2 text-center font-bold">{m.balance}</td>
                    <td className="num px-3 py-2 text-xs">
                      {m.isCount ? `جرد: العدّ ${m.counted}` : (docLabel(m) ?? "—")}
                      {m.isCount && m.delta === null ? " (الفرق غير معروف)" : ""}
                    </td>
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