import { useState } from "react";
import { Download, HardDriveDownload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import StatCard from "@/cashier/components/ui-kit/StatCard";
import { collectExport, totalRows } from "@/cashier/api/dataExport";
import { fmtDateTime, fmtInt } from "@/cashier/lib/format";
import { exportJson } from "@/cashier/lib/exportCsv";

// تصدير بيانات المحل الحالية إلى ملف واحد. هذا تصدير لسجلاتك وليس نسخة قابلة للاستعادة؛
// النسخ الاحتياطي والاستعادة تُدار على مستوى المنصة.
export default function BackupTab() {
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState(null); // { at, counts, failed }

  async function run() {
    setBusy(true);
    try {
      const { payload, counts, failed, truncated } = await collectExport();
      const stamp = payload.exported_at.slice(0, 10);
      exportJson(`بيانات-المحل-${stamp}.json`, payload);
      setLast({ at: payload.exported_at, counts, failed, truncated });
      if (failed.length) toast.warning(`تعذّر تصدير: ${failed.map((f) => f.label).join("، ")}. الملف ناقص.`);
      else if (truncated.length) toast.warning(`وصل ${truncated.map((t) => t.label).join("، ")} إلى حد التصدير، وقد يكون الملف ناقصًا.`);
      else toast.success(`تم تصدير ${fmtInt(totalRows(counts))} سجلًا`);
    } catch (e) {
      toast.error(e?.message ?? "تعذّر التصدير");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <SectionCard
        title="تصدير بيانات المحل"
        description="ملف واحد بكل ما في النظام الآن: المنتجات والمخزون والموردون والتوريد والمصروفات والورديات. للاحتفاظ بنسخة من سجلاتك."
        action={
          <Button className="gap-2 font-bold" onClick={run} disabled={busy}>
            <Download className="h-4 w-4" />
            {busy ? "جاري التصدير…" : "تصدير الآن"}
          </Button>
        }
      >
        <p className="text-xs text-muted-foreground">
          هذا تصدير لقراءة بياناتك أو حفظها خارج النظام، وليس نسخة تُستعاد بضغطة زر. النسخ الاحتياطي والاستعادة تُدار على مستوى المنصة.
        </p>
      </SectionCard>

      {last ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <StatCard label="آخر تصدير في هذه الجلسة" value={fmtDateTime(last.at)} hint="" icon={HardDriveDownload} tone="success" />
            <StatCard label="سجلات مصدَّرة" value={fmtInt(totalRows(last.counts))} hint={`موزّعة على ${fmtInt(last.counts.length)} جداول`} icon={Download} />
          </div>
          {last.failed.length ? (
            <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              لم يُصدَّر: {last.failed.map((f) => f.label).join("، ")}. أعد المحاولة قبل الاعتماد على الملف.
            </div>
          ) : null}
          {last.truncated?.length ? (
            <div role="alert" data-testid="export-truncated" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              وصل إلى الحد الأقصى للتصدير وقد توجد سجلات أقدم لم تدخل الملف: {last.truncated.map((t) => `${t.label} (${fmtInt(t.cap)})`).join("، ")}. لا تعتمد عليه كنسخة كاملة.
            </div>
          ) : null}
          <SectionCard title="محتوى الملف">
            <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
              {last.counts.map((c) => (
                <li key={c.key} className="flex justify-between rounded-md border border-border px-3 py-1.5">
                  <span>{c.label}</span>
                  <span className="num font-semibold">{fmtInt(c.count)}</span>
                </li>
              ))}
            </ul>
          </SectionCard>
        </>
      ) : null}
    </div>
  );
}
