import { CheckCircle2, Download, Loader2, XCircle } from "lucide-react";
import { Button } from "@/applications/apparel/components/ui/button";
import SectionCard from "@/applications/apparel/components/ui-kit/SectionCard";
import { SHEET_LABEL, canStart, errorText, topProblems, totalsOf } from "@/applications/apparel/api/importCenter";
import { fmtInt } from "@/applications/apparel/lib/format";

function Stat({ label, value, tone }) {
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className={`mt-0.5 font-heading text-[22px] font-semibold ${tone ?? ""}`}>{fmtInt(value)}</p>
    </div>
  );
}

const fieldOf = (e) => (e.field ? ` (${e.field})` : "");

/** Step 3: what will happen, before anything does. Every number is the server's. */
export default function ReviewStep({ session, preview, busy, error, onBack, onStart, onDownload }) {
  const totals = totalsOf(session.stats);
  const problems = topProblems(session.stats);
  const sample = preview?.sample_errors ?? [];
  const sheets = Object.entries(session.stats?.sheets ?? {});
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="صفوف الملف" value={totals.total} />
        <Stat label="سيتم إنشاؤها" value={totals.create} tone="text-emerald-700" />
        <Stat label="سيتم تحديثها" value={totals.update} tone="text-sky-700" />
        <Stat label="مرفوضة" value={totals.invalid} tone={totals.invalid ? "text-red-600" : ""} />
      </div>

      {sheets.length > 1 && (
        <SectionCard title="حسب الورقة">
          <ul className="divide-y divide-border text-[13px]">
            {sheets.map(([name, s]) => (
              <li key={name} className="flex items-center justify-between py-2">
                <span>{SHEET_LABEL[name] ?? name}</span>
                <span className="text-muted-foreground">
                  {fmtInt(s.valid)} صالح · {fmtInt(s.invalid)} مرفوض
                </span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {totals.invalid > 0 && (
        <SectionCard
          title="صفوف لن تُستورد"
          description="الصفوف الصالحة ستُستورد، والمرفوضة تُترك. صحّحها في الملف وارفعه مرة أخرى."
          action={
            <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={onDownload}>
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              تنزيل ملف الأخطاء
            </Button>
          }
        >
          <ul className="mb-3 flex flex-wrap gap-2">
            {problems.map((p) => (
              <li key={p.code} className="rounded-full bg-red-50 px-2.5 py-1 text-[11px] text-red-700">
                {p.text} · {fmtInt(p.count)}
              </li>
            ))}
          </ul>
          <ul className="divide-y divide-border text-[12px]">
            {sample.map((r) => (
              <li key={`${r.sheet}-${r.row}`} className="flex gap-3 py-1.5">
                <span className="w-28 shrink-0 text-muted-foreground">
                  {SHEET_LABEL[r.sheet] ?? r.sheet} · صف {r.row}
                </span>
                <span>{r.errors.map((e) => `${errorText(e.code)}${fieldOf(e)}`).join("، ")}</span>
              </li>
            ))}
          </ul>
          {totals.invalid > sample.length && <p className="mt-2 text-[11px] text-muted-foreground">يظهر أول {fmtInt(sample.length)} صفًّا فقط. الملف المنزَّل يحوي كل المرفوض.</p>}
        </SectionCard>
      )}

      {totals.valid === 0 && (
        <p role="alert" className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">
          <XCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          لا يوجد صف صالح للاستيراد. صحّح الملف وارفعه من جديد.
        </p>
      )}
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">{error}</p>}

      <div className="flex items-center justify-between gap-2">
        <Button type="button" variant="outline" onClick={onBack} disabled={busy}>رجوع للربط</Button>
        <Button type="button" onClick={onStart} disabled={busy || !canStart(session)} className="gap-2 bg-[#E8761A] text-white hover:bg-[#D1650F]">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
          ابدأ الاستيراد ({fmtInt(totals.valid)} صف)
        </Button>
      </div>
    </div>
  );
}
