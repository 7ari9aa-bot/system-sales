import { useEffect, useState } from "react";
import { BadgeCheck, FileSpreadsheet, Save, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { colorHex } from "@/cashier/lib/uiConstants";
import { changedCounts, diffOf, parseCount, sheetTotals, stocktakeErrorMessage } from "@/cashier/api/stocktakeAdapter";
import { useApproveStocktake, useCancelStocktake, useSaveCounts } from "@/cashier/api/useStocktake";
import { fmtInt } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";
import { cn } from "@/cashier/lib/utils";

const SIGNED = (n) => (n > 0 ? `+${fmtInt(n)}` : fmtInt(n));

// جدول الجرد: يقارن الكمية وقت بدء الجرد بما عدّه الموظف. الخلية الفارغة = لم تُعدّ بعد (وليست صفرًا).
export default function StocktakeTable({ sheet }) {
  // typed text per variant; undefined = untouched, "" = cleared (not counted)
  const [typed, setTyped] = useState({});
  const [diffOnly, setDiffOnly] = useState(false);
  const save = useSaveCounts(sheet.id);
  const approve = useApproveStocktake(sheet.id);
  const cancel = useCancelStocktake(sheet.id);
  const open = sheet.status === "OPEN";

  // a refetch brings the server's version: drop what was typed once it is saved
  useEffect(() => setTyped({}), [sheet.rows]);

  const parsed = {};
  const bad = new Set();
  for (const r of sheet.rows) {
    if (typed[r.id] === undefined) continue;
    try {
      parsed[r.id] = parseCount(typed[r.id]);
    } catch {
      bad.add(r.id);
    }
  }
  const rows = sheet.rows.map((r) => (r.id in parsed ? { ...r, actual: parsed[r.id] } : r));
  const totals = sheetTotals(rows);
  const pending = changedCounts(rows, sheet);
  const visible = diffOnly ? rows.filter((r) => (diffOf(r) ?? 0) !== 0) : rows;
  const busy = save.isPending || approve.isPending || cancel.isPending;

  const saveNow = () =>
    new Promise((resolve) => {
      if (bad.size) {
        toast.error("صحّح الكميات المحددة بالأحمر أولًا");
        return resolve(false);
      }
      if (pending.length === 0) return resolve(true);
      save.mutate(pending, {
        onSuccess: () => resolve(true),
        onError: (e) => {
          toast.error(stocktakeErrorMessage(e));
          resolve(false);
        },
      });
    });

  async function onSave() {
    if (pending.length === 0) return toast.info("لا توجد تغييرات للحفظ");
    if (await saveNow()) toast.success("تم حفظ الجرد، يمكن متابعته لاحقًا");
  }

  async function onApprove() {
    if (!(await saveNow())) return;
    approve.mutate(undefined, {
      onSuccess: (r) => toast.success(`تم اعتماد الجرد: عُدّل ${fmtInt(r.adjusted)} بندًا، وتُرك ${fmtInt(r.not_counted)} بندًا لم يُعدّ`),
      onError: (e) => toast.error(stocktakeErrorMessage(e, "approve")),
    });
  }

  function onCancel() {
    cancel.mutate(undefined, {
      onSuccess: () => toast.success("أُلغي الجرد ولم تتغير أي أرصدة"),
      onError: (e) => toast.error(stocktakeErrorMessage(e)),
    });
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: "أصناف في الجرد", value: `${fmtInt(totals.total)} متغيرًا` },
          { label: "تم عدّها", value: `${fmtInt(totals.counted)} من ${fmtInt(totals.total)}` },
          { label: "بنود بها فرق", value: `${fmtInt(totals.withDiff)} بندًا` },
          { label: "صافي الفرق (قطعة)", value: SIGNED(totals.net) },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-border bg-card px-4 py-3 card-soft">
            <p className="text-[11px] text-muted-foreground">{s.label}</p>
            <p className="num mt-1 font-heading text-base font-bold">{s.value}</p>
          </div>
        ))}
      </div>

      <SectionCard
        title={open ? "جرد المخزون الفعلي" : sheet.status === "APPROVED" ? "جرد معتمد" : "جرد ملغى"}
        description={
          open
            ? "أدخل الكمية الفعلية بعد العدّ. اترك الخانة فارغة لما لم تعدّه، فلن يُمسّ رصيده"
            : "هذا الجرد مغلق ولا يمكن تعديله"
        }
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
                    { header: "الكمية الفعلية", value: (r) => (r.actual === null ? "" : r.actual) },
                    { header: "الفرق", value: (r) => (diffOf(r) === null ? "" : diffOf(r)) },
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
                <th className="px-4 py-2 text-center font-semibold">الكمية وقت بدء الجرد</th>
                <th className="px-4 py-2 text-center font-semibold">الكمية الفعلية</th>
                <th className="px-4 py-2 text-center font-semibold">الفرق</th>
                <th className="px-4 py-2 text-center font-semibold">حالة البند</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {visible.map((row) => {
                const diff = diffOf(row);
                const invalid = bad.has(row.id);
                return (
                  <tr key={row.id} className={cn("transition-colors", diff !== null && diff !== 0 && "bg-amber-50/40")}>
                    <td className="px-4 py-2.5 font-medium">{row.productName}</td>
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-2 text-xs text-muted-foreground">
                        <ColorSwatch color={row.color} hex={colorHex(row.color)} />
                        <span>{row.size ? `مقاس ${row.size}` : "بدون مقاس"}</span>
                      </span>
                    </td>
                    <td className="num px-4 py-2.5 text-center">
                      {row.stock}
                      {row.drift !== 0 && open && (
                        <span className="mt-0.5 block text-[10px] font-normal text-muted-foreground" title="تغير الرصيد منذ بدء الجرد (مبيعات أو توريد)">
                          الآن {row.current}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <Input
                        inputMode="numeric"
                        disabled={!open || busy}
                        value={typed[row.id] ?? (row.actual === null ? "" : String(row.actual))}
                        placeholder="لم يُعدّ"
                        aria-invalid={invalid}
                        onChange={(e) => setTyped((prev) => ({ ...prev, [row.id]: e.target.value }))}
                        className={cn("num mx-auto h-8 w-24 text-center", invalid && "border-rose-500")}
                      />
                    </td>
                    <td className={cn("num px-4 py-2.5 text-center font-bold", !diff ? "text-muted-foreground" : diff > 0 ? "text-emerald-600" : "text-rose-600")}>
                      {diff === null ? "" : diff === 0 ? "—" : SIGNED(diff)}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      {diff === null ? (
                        <StatusBadge kind="inventory" value="in" label="لم يُعدّ" />
                      ) : (
                        <StatusBadge kind="inventory" value={diff === 0 ? "in" : "low"} label={diff === 0 ? "مطابق" : "يحتاج تسوية"} />
                      )}
                    </td>
                  </tr>
                );
              })}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-xs text-muted-foreground">لا توجد بنود</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {open && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
            <p className="text-xs text-muted-foreground">
              {fmtInt(totals.notCounted)} بندًا لم يُعدّ ولن يُمسّ. لا تتغير الأرصدة إلا بعد اعتماد المدير.
            </p>
            <div className="flex gap-2">
              <Button variant="ghost" className="gap-2 text-rose-600" disabled={busy} onClick={onCancel}>
                <XCircle className="h-4 w-4" />
                إلغاء الجرد
              </Button>
              <Button variant="outline" className="gap-2" disabled={busy || pending.length === 0} onClick={onSave}>
                <Save className="h-4 w-4" />
                حفظ
              </Button>
              <Button className="gap-2 font-bold" disabled={busy || totals.counted === 0} onClick={onApprove}>
                <BadgeCheck className="h-4 w-4" />
                اعتماد التسوية
              </Button>
            </div>
          </div>
        )}
      </SectionCard>
    </div>
  );
}
