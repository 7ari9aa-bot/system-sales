import { Printer } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import BarcodeBars from "@/cashier/components/ui-kit/BarcodeBars";
import { useShopName } from "@/cashier/lib/useShopName";
import { fmtMoney } from "@/cashier/lib/format";

// معاينة ملصقات الباركود بمقاسات ورق مختلفة.
export default function BarcodeLabelsDialog({ open, onOpenChange, rows, productName }) {
  const shopName = useShopName();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">طباعة ملصقات الباركود</DialogTitle>
          <DialogDescription>{productName} — {rows.length} ملصقًا • اضبط حجم الورق ثم اطبع</DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-3">
          <div className="w-[190px]">
            <Select defaultValue="38x25">
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="38x25">ملصق ٣٨ × ٢٥ مم</SelectItem>
                <SelectItem value="50x30">ملصق ٥٠ × ٣٠ مم</SelectItem>
                <SelectItem value="a4">ورق A4 — مقاس كامل</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <p className="num text-xs text-muted-foreground">إجمالي الملصقات: {rows.length}</p>
        </div>

        <div className="max-h-[52vh] overflow-y-auto scroll-slim rounded-xl border border-dashed border-border bg-muted/30 p-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {rows.map((row) => (
              <div key={row.id} className="rounded-lg border border-black/10 bg-white p-2.5 text-black">
                <p className="truncate text-[11px] font-bold">{shopName}</p>
                <p className="truncate text-[10px] text-black/70">{productName}</p>
                <p className="text-[10px] text-black/70">
                  {row.color} / {row.size}
                </p>
                <div className="my-1.5 flex justify-center">
                  <BarcodeBars code={row.barcode || row.sku} />
                </div>
                <p className="num text-center text-[10px] tracking-wider">{row.barcode || "—"}</p>
                <p className="num mt-0.5 text-center text-[11px] font-bold">{fmtMoney(row.sellPrice)}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="flex gap-2">
          <Button variant="outline" className="flex-1" onClick={() => onOpenChange(false)}>
            إغلاق
          </Button>
          <Button className="flex-1 gap-2 font-bold" onClick={() => window.print()}>
            <Printer className="h-4 w-4" />
            طباعة الملصقات
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}