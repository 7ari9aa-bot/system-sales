import { Barcode, RefreshCw, Wand2 } from "lucide-react";
import { Button } from "@/applications/apparel/components/ui/button";
import { Input } from "@/applications/apparel/components/ui/input";
import ColorSwatch from "@/applications/apparel/components/ui-kit/ColorSwatch";
import EmptyState from "@/applications/apparel/components/ui-kit/EmptyState";
import { colorHex } from "@/applications/apparel/lib/uiConstants";
import { useContainerWide } from "@/applications/apparel/hooks/use-is-wide";

const AUTO_HINT = "يتولّد تلقائيًا عند الحفظ";

/** A row that already exists in the backend (new rows get a local `row-` id). Its stock changes by count, not here. */
const isSaved = (row) => !String(row.id).startsWith("row-");

// جدول تركيبات اللون × المقاس مع SKU والباركود والرصيد الافتتاحي.
export default function VariantsMatrix(props) {
  // نسخة واحدة بس في الـDOM: الجدول على الكارت العريض، والكروت على الموبايل.
  const [wrapRef, wide] = useContainerWide(860);
  return <VariantsMatrixBody {...props} wide={wide} wrapRef={wrapRef} />;
}

/** الجسم نفسه دالة نقية من الـprops، عشان يتحسب من غير هوكس (وبيتقاس بالـhook فوق). */
export function VariantsMatrixBody({ rows, onChange, onGenerate, onGenerateBarcodes, defaultSell, wide = false, wrapRef }) {
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
    <div ref={wrapRef} className="space-y-3">
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

      {!wide && (
      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={row.id} data-variant-card className="space-y-2 rounded-xl border border-border bg-card p-3">
            <div className="flex items-center justify-between gap-2">
              <ColorSwatch color={row.color} hex={colorHex(row.color)} />
              <span className="num rounded-md bg-muted px-2 py-0.5 text-sm font-bold">{row.size}</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label className="col-span-2 space-y-1">
                <span className="text-[11px] font-semibold text-muted-foreground">SKU</span>
                <Input value={row.sku} onChange={(e) => onChange(row.id, { sku: e.target.value })} className="num h-8 w-full text-xs" />
              </label>
              <label className="col-span-2 space-y-1">
                <span className="text-[11px] font-semibold text-muted-foreground">الباركود</span>
                <Input
                  value={row.barcode}
                  placeholder={row.autoBarcode ? AUTO_HINT : "اضغط «توليد الباركودات»"}
                  onChange={(e) => onChange(row.id, { barcode: e.target.value, autoBarcode: false })}
                  className="num h-8 w-full text-xs"
                />
              </label>
              <label className="space-y-1">
                <span className="text-[11px] font-semibold text-muted-foreground">سعر البيع</span>
                <Input type="number" value={row.sellPrice} onChange={(e) => onChange(row.id, { sellPrice: Number(e.target.value) })} className="num h-8 w-full" />
              </label>
              <div className="space-y-1">
                <span className="text-[11px] font-semibold text-muted-foreground">رصيد افتتاحي</span>
                {isSaved(row) ? (
                  <p className="flex h-8 items-center text-xs text-muted-foreground" title="الرصيد يتغيّر من الجرد أو حركات المخزون">من الجرد</p>
                ) : (
                  <Input
                    type="number"
                    min={0}
                    value={row.stock}
                    onChange={(e) => onChange(row.id, { stock: Number(e.target.value) })}
                    className="num h-8 w-full text-center"
                  />
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
      )}

      {wide && (
      <div className="scroll-slim overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="bg-muted/50 text-xs text-muted-foreground">
              <th className="px-3 py-2 text-start font-semibold">اللون</th>
              <th className="px-3 py-2 text-center font-semibold">المقاس</th>
              <th className="px-3 py-2 text-start font-semibold">SKU</th>
              <th className="px-3 py-2 text-start font-semibold">الباركود</th>
              <th className="px-3 py-2 text-start font-semibold">سعر البيع</th>
              <th className="px-3 py-2 text-center font-semibold">رصيد افتتاحي</th>
              <th className="px-3 py-2 text-center font-semibold">حد التنبيه</th>
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
                    placeholder={row.autoBarcode ? AUTO_HINT : "اضغط «توليد الباركودات»"}
                    onChange={(e) => onChange(row.id, { barcode: e.target.value, autoBarcode: false })}
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
                <td className="px-3 py-2 text-center">
                  <Input
                    type="number"
                    min={0}
                    value={row.reorderLevel ?? 0}
                    onChange={(e) => onChange(row.id, { reorderLevel: e.target.value })}
                    className="num mx-auto h-8 w-20 text-center"
                    title="عند وصول الرصيد إلى هذا الرقم يظهر تنبيه نقص؛ والقيمة صفر تعني عدم إظهار تنبيه"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}

      <p className="text-[11px] text-muted-foreground">
        سعر البيع الافتراضي: {defaultSell || "—"} ج.م — يمكن تعديل أي تركيبة على حدة عند الحاجة فقط.
      </p>
    </div>
  );
}