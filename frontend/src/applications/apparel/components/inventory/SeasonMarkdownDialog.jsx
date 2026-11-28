import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/applications/apparel/components/ui/button";
import { Input } from "@/applications/apparel/components/ui/input";
import { Label } from "@/applications/apparel/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/applications/apparel/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/applications/apparel/components/ui/select";
import ReportTable from "@/applications/apparel/components/reports/ReportTable";
import { toneClass } from "@/applications/apparel/components/reports/ProfitReportSection";
import { useSeasonMarkdown } from "@/applications/apparel/api/useSeasonMarkdown";
import { markdownErrorKind, percentText } from "@/applications/apparel/api/seasonMarkdown";
import {
  appliedMessage,
  belowCostWarning,
  canConfirm,
  canPreview,
  confirmLabel,
  floorNote,
  markdownColumns,
  markdownErrorMessage,
  previewSummary,
  unknownCostNote,
} from "@/applications/apparel/components/inventory/seasonMarkdownView";

const SUB = "mt-0.5 block text-[11px] text-[#7A766C]";
const NOTE = "border px-3.5 py-2.5 text-[11.5px] font-medium";

/**
 * تخفيض موسم كامل بنسبة: اختار الموسم واكتب النسبة واضغط معاينة، هتشوف سعر كل مقاس قبل وبعد
 * والأحمر هو اللي هيتباع بأقل من تكلفته. مفيش حاجة بتتغيّر قبل «تأكيد»، والتأكيد بيبعت المعاينة
 * نفسها: لو الأسعار اتغيّرت في النص بيرجع يقول اعمل معاينة جديدة بدل ما يخفّض حاجة مختلفة.
 */
export default function SeasonMarkdownDialog({ open, onOpenChange, seasons = [], brands = [] }) {
  const [season, setSeason] = useState("");
  const [brandId, setBrandId] = useState("");
  const [percent, setPercent] = useState("");
  const [error, setError] = useState(null);
  const { preview, apply } = useSeasonMarkdown();

  const shown = preview.data ?? null;
  const percentValid = percentText(percent) !== null;
  const busy = preview.isPending || apply.isPending;

  // Any change to what was previewed makes the preview stale: the token no longer describes it.
  const edit = (setter) => (value) => {
    setter(value);
    preview.reset();
    setError(null);
  };

  const close = (next) => {
    if (!next) {
      preview.reset();
      apply.reset();
      setError(null);
    }
    onOpenChange(next);
  };

  const runPreview = () => {
    setError(null);
    preview.mutate({ season, percent, brandId }, { onError: (e) => setError(markdownErrorKind(e)) });
  };

  const runApply = () => {
    setError(null);
    apply.mutate(
      { preview: shown, brandId },
      {
        onSuccess: (result) => {
          toast.success(appliedMessage(result));
          close(false);
        },
        onError: (e) => {
          const kind = markdownErrorKind(e);
          setError(kind);
          // The catalog moved: what was previewed is no longer true, so it must not stay on screen to be confirmed.
          if (kind === "stale") preview.reset();
        },
      },
    );
  };

  const columns = markdownColumns().map((c) => ({
    key: c.key,
    header: c.header,
    align: c.align,
    render: (r) => (
      <span className={toneClass(c.tone(r))}>
        {c.text(r)}
        {c.sub && c.sub(r) && <span className={SUB}>{c.sub(r)}</span>}
      </span>
    ),
  }));

  const warning = shown ? belowCostWarning(shown.totals) : null;
  const unknown = shown ? unknownCostNote(shown.totals) : null;
  const floor = shown ? floorNote(shown.totals) : null;

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent dir="rtl" className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تخفيض موسم</DialogTitle>
          <DialogDescription>
            اختار الموسم والنسبة، وشوف سعر كل مقاس قبل وبعد. مفيش حاجة بتتغيّر غير لما تضغط تأكيد.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <Label className="text-[12px]">الموسم</Label>
            <Select value={season} onValueChange={edit(setSeason)}>
              <SelectTrigger aria-label="الموسم">
                <SelectValue placeholder="اختار الموسم" />
              </SelectTrigger>
              <SelectContent>
                {seasons.map((name) => (
                  <SelectItem key={name} value={name}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[12px]">العلامة (اختياري)</Label>
            <Select value={brandId || "all"} onValueChange={(v) => edit(setBrandId)(v === "all" ? "" : v)}>
              <SelectTrigger aria-label="العلامة">
                <SelectValue placeholder="كل العلامات" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">كل العلامات</SelectItem>
                {brands.map((b) => (
                  <SelectItem key={b.id} value={b.id}>
                    {b.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[12px]">نسبة التخفيض ٪</Label>
            <Input
              inputMode="decimal"
              dir="ltr"
              aria-label="نسبة التخفيض"
              placeholder="مثلًا 20"
              value={percent}
              onChange={(e) => edit(setPercent)(e.target.value)}
              aria-invalid={percent !== "" && !percentValid}
            />
            {percent !== "" && !percentValid && (
              <p className="mt-1 text-[11px] text-rose-600" role="alert">من 0.01 لـ90، وبحد أقصى رقمين بعد العلامة</p>
            )}
          </div>
        </div>

        <div className="flex justify-end">
          <Button type="button" onClick={runPreview} disabled={!canPreview({ season, percentValid, busy })}>
            {preview.isPending ? "جارٍ المعاينة…" : "معاينة"}
          </Button>
        </div>

        {error && (
          <p
            className={`${NOTE} ${error === "stale" ? "border-amber-300 bg-amber-50 text-amber-800" : "border-rose-300 bg-rose-50 text-rose-700"}`}
            role="alert"
          >
            {markdownErrorMessage(error)}
          </p>
        )}

        {shown && shown.rows.length === 0 && (
          <p className="border border-[#DED8CD] bg-white px-3.5 py-6 text-center text-[12px] text-[#7A766C]" role="status">
            مفيش مقاسات نشطة في الموسم ده بالفلتر المختار.
          </p>
        )}

        {shown && shown.rows.length > 0 && (
          <div className="space-y-3">
            {warning && <p className={`${NOTE} border-rose-300 bg-rose-50 text-rose-700`} role="alert">{warning}</p>}
            {unknown && <p className={`${NOTE} border-amber-300 bg-amber-50 text-amber-800`} role="status">{unknown}</p>}
            {floor && <p className={`${NOTE} border-[#DED8CD] bg-white text-[#7A766C]`} role="status">{floor}</p>}
            <ReportTable
              title={`معاينة تخفيض ${shown.percent}٪ على ${shown.season}`}
              description={previewSummary(shown.totals)}
              columns={columns}
              rows={shown.rows}
            />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => close(false)} disabled={busy}>
                إلغاء
              </Button>
              <Button type="button" onClick={runApply} disabled={!canConfirm({ preview: shown, busy })}>
                {apply.isPending ? "جارٍ التنفيذ…" : confirmLabel(shown)}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
