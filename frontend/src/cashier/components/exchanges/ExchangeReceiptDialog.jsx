import { FilePlus2, Printer } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { fmtMoney } from "@/cashier/lib/format";
import { shop } from "@/cashier/lib/mockData";

// معاينة مستند الاستبدال ٨٠ مم: القطع المستبدلة، البديلة، وفارق السعر.
export default function ExchangeReceiptDialog({ open, onOpenChange, operation: doc, onNewOperation }) {
  if (!doc) return null;

  const customerPays = doc.difference > 0;
  const even = doc.difference === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">معاينة مستند الاستبدال</DialogTitle>
        </DialogHeader>

        <div className="max-h-[62vh] overflow-y-auto scroll-slim rounded-xl border border-dashed border-border bg-muted/30 p-3">
          <div className="print-area mx-auto w-full max-w-[330px] rounded-lg bg-white p-4 font-body text-[12px] leading-relaxed text-black shadow-sm">
            <div className="text-center">
              <p className="font-heading text-base font-extrabold">{shop.name}</p>
              <p>{shop.branch}</p>
              <p className="num">{shop.phone}</p>
              <p className="num">الرقم الضريبي: {shop.taxId}</p>
            </div>

            <p className="mt-2 text-center font-heading text-[13px] font-bold">مستند استبدال</p>
            <div className="my-3 border-t border-dashed border-black/40" />

            <div className="flex justify-between">
              <span>رقم العملية</span>
              <span className="num font-bold">{doc.number}</span>
            </div>
            <div className="flex justify-between">
              <span>التاريخ</span>
              <span className="num">{new Date(doc.date).toLocaleString("ar-EG-u-nu-latn", { dateStyle: "short", timeStyle: "short" })}</span>
            </div>
            <div className="flex justify-between">
              <span>الموظف</span>
              <span>{doc.employee}</span>
            </div>
            <div className="flex justify-between">
              <span>الفاتورة الأصلية</span>
              <span className="num font-bold">{doc.invoiceNumber}</span>
            </div>
            <div className="flex justify-between">
              <span>العميل</span>
              <span>{doc.customer}</span>
            </div>

            <div className="my-3 border-t border-dashed border-black/40" />
            <p className="mb-1 font-bold">القطع المستبدلة</p>
            <table className="w-full">
              <thead>
                <tr className="border-b border-black/30 text-[11px]">
                  <th className="py-1 text-start">الصنف</th>
                  <th className="py-1 text-center">كمية</th>
                  <th className="py-1 text-start">إجمالي</th>
                </tr>
              </thead>
              <tbody>
                {doc.returns.map((it, i) => (
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
            <p className="mb-1 font-bold">المنتجات البديلة</p>
            <table className="w-full">
              <thead>
                <tr className="border-b border-black/30 text-[11px]">
                  <th className="py-1 text-start">الصنف</th>
                  <th className="py-1 text-center">كمية</th>
                  <th className="py-1 text-start">إجمالي</th>
                </tr>
              </thead>
              <tbody>
                {doc.replacements.map((it, i) => (
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
                <span>قيمة القطع المستبدلة</span>
                <span className="num">{doc.returnedValue.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span>قيمة المنتجات البديلة</span>
                <span className="num">{doc.newValue.toFixed(2)}</span>
              </div>
              <div className="flex justify-between border-t border-black/40 pt-1 font-bold">
                <span>{even ? "لا يوجد فرق" : customerPays ? "المطلوب من العميل" : "المستحق للعميل"}</span>
                <span className="num">{Math.abs(doc.difference).toFixed(2)} ج.م</span>
              </div>
            </div>

            {doc.note && <p className="mt-2 border-t border-dashed border-black/40 pt-2 text-[11px]">ملاحظة: {doc.note}</p>}

            <div className="my-3 border-t border-dashed border-black/40" />
            <p className="text-center text-[11px]">يُسجَّل فرق السعر في المستند فقط • لا يتم تحصيل أو رد مبالغ من هذه الشاشة</p>
            <p className="text-center text-[11px]">شكرًا لتعاملكم معنا</p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3">
          <StatusBadge
            kind="exchange"
            value={doc.status === "completed" ? "completed" : "review"}
            label={doc.status === "completed" ? "تم الاعتماد" : "مسودة"}
          />
          <span className="num text-xs text-muted-foreground">
            {doc.status === "completed" ? `الفرق المسجَّل ${fmtMoney(Math.abs(doc.difference))}` : "معاينة قبل الاعتماد"}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" className="flex-1 gap-2" onClick={() => window.print()}>
            <Printer className="h-4 w-4" />
            طباعة
          </Button>
          <Button
            className="flex-1 gap-2 font-bold"
            onClick={() => {
              onOpenChange(false);
              onNewOperation?.();
            }}
          >
            <FilePlus2 className="h-4 w-4" />
            عملية جديدة
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}