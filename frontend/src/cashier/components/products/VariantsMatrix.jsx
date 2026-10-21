import { Barcode, RefreshCw, Wand2 } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import { colorHex } from "@/cashier/lib/uiConstants";

/** A row that already exists in the backend (new rows get a local `row-` id). Its stock changes by count, not here. */
const isSaved = (row) => !String(row.id).startsWith("row-");

// جدول تركيبات اللون × المقاس مع SKU والباركود والرصيد الافتتاحي.
export default function VariantsMatrix({ rows, onChange, onGenerate, onGenerateBarcodes, defaultSell }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={Wand2}
        title="لم يتم توليد التركيبات بعد"
        description="اختر الألوان والمقاسات ثم اضغط «توليد جدول المتغيرات» لعرض كل تركيبة بباركودها ورصيدها."
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="num text-xs text-muted-foreground">{rows.length} تركيبة (لون × مقاس)</p>
        <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={onGenerate}>
            <RefreshCw className="h-3.5 w-3.5" />
            إعادة التوليد
          </Button>
          <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={onGenerateBarcodes}>
            <Barcode className="h-3.5 w-3.5" />
            توليد الباركودات
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto scroll-slim rounded-xl border border-border">
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="bg-muted/50 text-xs text-muted-foreground">
              <th className="px-3 py-2 text-start font-semibold">اللون</th>
              <th className="px-3 py-2 text-center font-semibold">المقاس</th>
              <th className="px-3 py-2 text-start font-semibold">SKU</th>
              <th className="px-3 py-2 text-start font-semibold">الباركود</th>
              <th className="px-3 py-2 text-start font-semibold">سعر البيع</th>
              <th className="px-3 py-2 text-center font-semibold">رصيد افتتاحي</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((row) => (
              <tr key={row.id} className="transition-colors hover:bg-accent/30">
                <td className="px-3 py-2">
                  <ColorSwatch color={row.color} hex={colorHex(row.color)} />
                </td>
                <td className="px-3 py-2 text-center font-semibold">{row.size}</td>
                <td className="px-3 py-2">
                  <Input value={row.sku} onChange={(e) => onChange(row.id, { sku: e.target.value })} className="num h-8 w-[170px] text-xs" />
                </td>
                <td className="px-3 py-2">
                  <Input
                    value={row.barcode}
                    placeholder={`اضغط «توليد الباركودات»`}
                    onChange={(e) => onChange(row.id, { barcode: e.target.value })}
                    className="num h-8 w-[150px] text-xs"
                  />
                </td>
                <td className="px-3 py-2">
                  <Input
                    type="number"
                    value={row.sellPrice}
                    onChange={(e) => onChange(row.id, { sellPrice: Number(e.target.value) })}
                    className="num h-8 w-24"
                  />
                </td>
                <td className="px-3 py-2 text-center">
                  {isSaved(row) ? (
                    <span className="text-xs text-muted-foreground" title="الرصيد يتغيّر من الجرد أو حركات المخزون">من الجرد</span>
                  ) : (
                    <Input
                      type="number"
                      min={0}
                      value={row.stock}
                      onChange={(e) => onChange(row.id, { stock: Number(e.target.value) })}
                      className="num mx-auto h-8 w-20 text-center"
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-muted-foreground">
        سعر البيع الافتراضي: {defaultSell || "—"} ج.م — يمكن تعديل أي تركيبة على حدة عند الحاجة فقط.
      </p>
    </div>
  );
}