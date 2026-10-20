import { useState } from "react";
import { BadgeCheck, FileSpreadsheet, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { colorHex } from "@/cashier/lib/mockData";
import { fmtInt } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";
import { cn } from "@/cashier/lib/utils";

// جدول الجرد: مقارنة الكمية المسجلة بالكمية الفعلية وإظهار الفرق قبل اعتماد التسوية.
export default function StocktakeTable({ initialRows }) {
  const [rows, setRows] = useState(initialRows);
  const [diffOnly, setDiffOnly] = useState(false);

  const visible = diffOnly ? rows.filter((r) => r.actual !== r.stock) : rows;
  const diffCount = rows.filter((r) => r.actual !== r.stock).length;
  const netDiff = rows.reduce((s, r) => s + (r.actual - r.stock), 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: "أصناف في الجرد", value: `${fmtInt(rows.length)} متغيرًا` },
          { label: "بنود بها فرق", value: `${fmtInt(diffCount)} بندًا` },
          { label: "صافي الفرق (قطعة)", value: `${netDiff > 0 ? "+" : ""}${fmtInt(netDiff)}` },
          { label: "قيمة الفرق التقديرية", value: `${fmtInt(Math.abs(netDiff) * 350)} ج.م` },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-border bg-card px-4 py-3 card-soft">
            <p className="text-[11px] text-muted-foreground">{s.label}</p>
            <p className="num mt-1 font-heading text-base font-bold">{s.value}</p>
          </div>
        ))}
      </div>

      <SectionCard
        title="جرد المخزون الفعلي"
        description="أدخل الكمية الفعلية بعد العدّ — يظهر الفرق فورًا قبل اعتماد التسوية"
        noPadding
        action={
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" checked={diffOnly} onChange={(e) => setDiffOnly(e.target.checked)} className="h-3.5 w-3.5 accent-orange-500" />
              بنود بها فرق فقط
            </label>
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-1.5"
              onClick={() => {
                exportCsv(
                  "ورقة-الجرد.csv",
                  [
                    { header: "المنتج", key: "productName" },
                    { header: "SKU", key: "sku" },
                    { header: "اللون", key: "color" },
                    { header: "المقاس", key: "size" },
                    { header: "الكمية المسجلة", key: "stock" },
                    { header: "الكمية الفعلية", key: "actual" },
                    { header: "الفرق", value: (r) => r.actual - r.stock },
                  ],
                  rows,
                );
                toast.success("تم تصدير ورقة الجرد");
              }}
            >
              <FileSpreadsheet className="h-3.5 w-3.5" />
              تصدير
            </Button>
          </div>
        }
      >
        <div className="overflow-x-auto scroll-slim">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="bg-muted/50 text-xs text-muted-foreground">
                <th className="px-4 py-2 text-start font-semibold">المنتج</th>
                <th className="px-4 py-2 text-start font-semibold">اللون / المقاس</th>
                <th className="px-4 py-2 text-start font-semibold">الفرع</th>
                <th className="px-4 py-2 text-center font-semibold">الكمية المسجلة</th>
                <th className="px-4 py-2 text-center font-semibold">الكمية الفعلية</th>
                <th className="px-4 py-2 text-center font-semibold">الفرق</th>
                <th className="px-4 py-2 text-center font-semibold">حالة البند</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {visible.map((row) => {
                const diff = row.actual - row.stock;
                return (
                  <tr key={row.id} className={cn("transition-colors", diff !== 0 && "bg-amber-50/40")}>
                    <td className="px-4 py-2.5 font-medium">{row.productName}</td>
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-2 text-xs text-muted-foreground">
                        <ColorSwatch color={row.color} hex={colorHex(row.color)} />
                        <span>مقاس {row.size}</span>
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{row.branch}</td>
                    <td className="num px-4 py-2.5 text-center">{row.stock}</td>
                    <td className="px-4 py-2.5 text-center">
                      <Input
                        type="number"
                        min={0}
                        value={row.actual}
                        onChange={(e) =>
                          setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, actual: Math.max(0, Number(e.target.value) || 0) } : r)))
                        }
                        className="num mx-auto h-8 w-20 text-center"
                      />
                    </td>
                    <td className={cn("num px-4 py-2.5 text-center font-bold", diff === 0 ? "text-muted-foreground" : diff > 0 ? "text-emerald-600" : "text-rose-600")}>
                      {diff === 0 ? "—" : diff > 0 ? `+${diff}` : diff}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <StatusBadge kind="inventory" value={diff === 0 ? "in" : "low"} label={diff === 0 ? "مطابق" : "يحتاج تسوية"} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
          <p className="text-xs text-muted-foreground">
            {diffCount} بندًا بها فرق — لن تُعدّل الأرصدة إلا بعد اعتماد التسوية.
          </p>
          <div className="flex gap-2">
            <Button variant="outline" className="gap-2" onClick={() => toast.info("تم حفظ الجرد كمسودة — يمكن متابعته لاحقًا")}>
              <Save className="h-4 w-4" />
              حفظ كمسودة
            </Button>
            <Button className="gap-2 font-bold" onClick={() => toast.success(`تم اعتماد تسوية الجرد وتحديث ${diffCount} بندًا`)}>
              <BadgeCheck className="h-4 w-4" />
              اعتماد التسوية
            </Button>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}