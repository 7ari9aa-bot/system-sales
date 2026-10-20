import { Printer } from "lucide-react";
import { useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { Switch } from "@/cashier/components/ui/switch";
import BarcodeBars from "@/cashier/components/ui-kit/BarcodeBars";
import { BTN, BTN_PRIMARY, FIELD_SELECT, SWITCH } from "@/cashier/components/labels/labelStyles";
import { shop } from "@/cashier/lib/mockData";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

const PAPER_SIZES = [
  { key: "38x25", label: "ملصق ٣٨ × ٢٥ مم" },
  { key: "50x30", label: "ملصق ٥٠ × ٣٠ مم" },
  { key: "a4", label: "ورق A4 — شبكة ملصقات" },
];

const PAPER_GRID = {
  "38x25": "grid-cols-2 sm:grid-cols-4",
  "50x30": "grid-cols-2 sm:grid-cols-3",
  a4: "grid-cols-2 sm:grid-cols-3",
};

const MAX_PREVIEW = 60;

// معاينة وطباعة ملصقات الباركود: المقاس، محتوى الملصق، ثم الطباعة.
export default function LabelPreviewDialog({ open, onOpenChange, rows }) {
  const [paper, setPaper] = useState("38x25");
  const [showShop, setShowShop] = useState(true);
  const [showPrice, setShowPrice] = useState(true);

  const labels = rows.flatMap((row) => Array.from({ length: row.qty }, (_, i) => ({ ...row, key: `${row.id}-${i}` })));
  const visible = labels.slice(0, MAX_PREVIEW);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-3xl rounded-lg border-[#DED8CD] bg-white p-4 text-[#33322E]">
        <DialogHeader>
          <DialogTitle className="font-heading text-[15px] font-semibold">معاينة ملصقات الباركود</DialogTitle>
          <DialogDescription className="num text-[12px] text-[#7A766C]">
            {fmtInt(rows.length)} صنفًا • {fmtInt(labels.length)} ملصقًا — اضبط المقاس ثم اطبع الملصقات
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-[18px] text-[12px] font-medium">
          <Select value={paper} onValueChange={setPaper}>
            <SelectTrigger className={cn(FIELD_SELECT, "w-[210px]")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAPER_SIZES.map((p) => (
                <SelectItem key={p.key} value={p.key}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <label className="flex items-center gap-1.5">
            <Switch checked={showShop} onCheckedChange={setShowShop} className={SWITCH} />
            اسم المحل
          </label>

          <label className="flex items-center gap-1.5">
            <Switch checked={showPrice} onCheckedChange={setShowPrice} className={SWITCH} />
            السعر
          </label>
        </div>

        <div className="print-area max-h-[52vh] overflow-y-auto scroll-slim">
          <div className={cn("grid gap-2 rounded-lg border border-dashed border-[#DED8CD] bg-[#F7F5F0] p-2.5", PAPER_GRID[paper] ?? PAPER_GRID["38x25"])}>
            {visible.map((label) => (
              <div key={label.key} className="rounded-md border border-[#DED8CD] bg-white p-2 text-black">
                {showShop && <p className="truncate text-[11px] font-bold">{shop.name}</p>}
                <p className="truncate text-[10px] text-[#555555]">{label.productName}</p>
                <p className="text-[10px] text-[#555555]">
                  {label.color} / {label.size}
                </p>
                <div className="my-1.5 flex justify-center">
                  <BarcodeBars code={label.barcode} />
                </div>
                <p className="num text-center text-[10px] tracking-[1px]">{label.barcode}</p>
                {showPrice && <p className="num mt-0.5 text-center text-[11px] font-bold">{fmtMoney(label.sellPrice)}</p>}
              </div>
            ))}
          </div>

          {labels.length > visible.length && (
            <p className="num mt-3 text-center text-[11px] text-[#7A766C]">
              المعاينة تعرض أول {fmtInt(visible.length)} ملصقًا، وستُطبع جميع الملصقات ({fmtInt(labels.length)}).
            </p>
          )}
        </div>

        <div className="mt-3 flex gap-2">
          <Button variant="outline" className={cn(BTN, "flex-1 justify-center")} onClick={() => onOpenChange(false)}>
            إغلاق
          </Button>
          <Button className={cn(BTN_PRIMARY, "flex-1 justify-center")} onClick={() => window.print()}>
            <Printer />
            طباعة {fmtInt(labels.length)} ملصق
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}