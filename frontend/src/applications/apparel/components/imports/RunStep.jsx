import { useState } from "react";
import { CheckCircle2, Download, Loader2, OctagonX, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/applications/apparel/components/ui/button";
import SectionCard from "@/applications/apparel/components/ui-kit/SectionCard";
import ConfirmDialog from "@/applications/apparel/components/ui-kit/ConfirmDialog";
import { STATUS_LABEL, progressOf, remainingOf, totalsOf } from "@/applications/apparel/api/importCenter";
import { fmtInt } from "@/applications/apparel/lib/format";
import { appPath } from "../../basePath";

/** Step 4: the import is running, or it ended. The numbers are what the server has applied so far. */
export default function RunStep({ session, busy, error, onCancel, onDownload, onAgain }) {
  const [confirming, setConfirming] = useState(false);
  const s = session.stats ?? {};
  const pct = progressOf(s);
  const totals = totalsOf(s);
  const rejected = totals.invalid + Number(s.failed ?? 0);
  const running = session.status === "running";
  const ok = session.status === "completed";

  return (
    <div className="flex flex-col gap-4">
      <SectionCard title={STATUS_LABEL[session.status] ?? session.status}>
        {running && (
          <div>
            <div className="mb-2 flex items-center gap-2 text-[13px]">
              <Loader2 className="h-4 w-4 animate-spin text-[#E8761A]" aria-hidden="true" />
              جارٍ الاستيراد، يمكنك ترك الصفحة وسيكمل في الخلفية
            </div>
            <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} className="h-2.5 overflow-hidden rounded-full bg-[#E9E5DC]">
              <div className="h-full bg-[#E8761A] transition-[width] duration-500" style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-1.5 text-[12px] text-muted-foreground">
              {pct}% · تمّ {fmtInt(s.applied ?? 0)} · متبقٍّ {fmtInt(remainingOf(s))}
            </p>
          </div>
        )}
        {ok && (
          <p className="flex items-center gap-2 text-[14px] font-semibold text-emerald-700">
            <CheckCircle2 className="h-5 w-5" aria-hidden="true" />
            اكتمل الاستيراد
          </p>
        )}
        {session.status === "cancelled" && (
          <p className="flex items-center gap-2 text-[14px] font-semibold text-amber-700">
            <OctagonX className="h-5 w-5" aria-hidden="true" />
            أُلغي الاستيراد. ما تمّ تطبيقه قبل الإلغاء يبقى في متجرك.
          </p>
        )}
        {session.status === "failed" && (
          <p className="flex items-center gap-2 text-[14px] font-semibold text-red-700">
            <XCircle className="h-5 w-5" aria-hidden="true" />
            توقف الاستيراد بسبب خطأ. ما تمّ تطبيقه قبل التوقف يبقى في متجرك.
          </p>
        )}

        {!running && (
          <dl className="mt-3 grid gap-2 text-[13px] sm:grid-cols-3">
            <div><dt className="text-[11px] text-muted-foreground">تمّ تطبيقه</dt><dd className="font-semibold">{fmtInt(s.applied ?? 0)}</dd></div>
            <div><dt className="text-[11px] text-muted-foreground">تخطّي</dt><dd className="font-semibold">{fmtInt(s.skipped ?? 0)}</dd></div>
            <div><dt className="text-[11px] text-muted-foreground">لم يُستورد</dt><dd className="font-semibold">{fmtInt(rejected)}</dd></div>
          </dl>
        )}
      </SectionCard>

      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">{error}</p>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        {running ? (
          <Button type="button" variant="outline" onClick={() => setConfirming(true)} disabled={busy}>إلغاء الاستيراد</Button>
        ) : (
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={onAgain}>استيراد ملف آخر</Button>
            {rejected > 0 && (
              <Button type="button" variant="outline" className="gap-1.5" onClick={onDownload}>
                <Download className="h-4 w-4" aria-hidden="true" />
                ملف الأخطاء
              </Button>
            )}
          </div>
        )}
        {!running && (
          <Button asChild className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
            <Link to={appPath("/inventory")}>عرض المخزون</Link>
          </Button>
        )}
      </div>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="إلغاء الاستيراد؟"
        description="ما تمّ استيراده حتى الآن يبقى في متجرك ولا يُحذف. الصفوف المتبقية لن تُستورد."
        confirmLabel="نعم، ألغِ"
        cancelLabel="متابعة الاستيراد"
        onConfirm={() => {
          setConfirming(false);
          onCancel();
        }}
      />
    </div>
  );
}
