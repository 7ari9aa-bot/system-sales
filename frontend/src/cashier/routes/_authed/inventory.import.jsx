import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Check } from "lucide-react";
import { toast } from "sonner";
import UploadStep from "@/cashier/components/imports/UploadStep";
import MappingStep, { shownPolicy } from "@/cashier/components/imports/MappingStep";
import ReviewStep from "@/cashier/components/imports/ReviewStep";
import RunStep from "@/cashier/components/imports/RunStep";
import { downloadErrorReport, importErrorText } from "@/cashier/api/importCenter";
import { STEPS, mappingBody, mergedMapping, stepOf } from "@/cashier/api/importFlow";
import {
  useCancelImport,
  useImportPreview,
  useImportSession,
  useSaveMapping,
  useStartImport,
  useUploadImageArchive,
  useUploadImport,
  useValidateImport,
} from "@/cashier/api/useImportCenter";
import { assignField } from "@/cashier/api/importCenter";

export default function InventoryImportPage() {
  const [params, setParams] = useSearchParams();
  const id = params.get("s") ?? "";
  const [draft, setDraft] = useState({});
  const [policy, setPolicy] = useState(null);
  const [error, setError] = useState("");

  const query = useImportSession(id);
  const session = query.data;
  const step = stepOf(session);
  const preview = useImportPreview(id, step === "review" || step === "run");

  const upload = useUploadImport();
  const archive = useUploadImageArchive(id);
  const save = useSaveMapping(id);
  const validate = useValidateImport(id);
  const start = useStartImport(id);
  const cancel = useCancelImport(id);
  const busy = upload.isPending || archive.isPending || save.isPending || validate.isPending || start.isPending || cancel.isPending;

  const run = async (fn, after) => {
    setError("");
    try {
      const result = await fn();
      after?.(result);
    } catch (e) {
      setError(importErrorText(e));
    }
  };

  const onFile = (file) =>
    run(() => upload.mutateAsync(file), (s) => {
      setDraft({});
      setPolicy(null);
      setParams({ s: s.id });
    });

  // "Check the file" saves the mapping first, then asks the server to validate every row.
  const onCheck = () =>
    run(async () => {
      await save.mutateAsync(mappingBody(session, draft, policy ?? session.options?.duplicate_policy));
      return validate.mutateAsync();
    });

  const onArchive = (file) => run(() => archive.mutateAsync(file));
  const onStart = () => run(() => start.mutateAsync());
  const onCancel = () => run(() => cancel.mutateAsync());
  const onDownload = () =>
    downloadErrorReport(id).catch((e) => toast.error(importErrorText(e)));
  const again = () => {
    setDraft({});
    setPolicy(null);
    setError("");
    setParams({});
  };

  const loadFailed = id && query.isError;
  const current = STEPS.findIndex((s) => s.key === step);

  return (
    <div className="-mx-2 -my-2 flex min-h-[calc(100vh-1rem)] flex-col gap-5 bg-[#F4F1EC] px-6 py-6 text-[#3B3A36] sm:-mx-3 sm:px-9 sm:py-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-[26px] font-semibold leading-tight sm:text-[30px]">استيراد المنتجات والمخزون</h1>
          <p className="mt-1.5 text-[13px] text-[#7A766C]">من ملف Excel أو CSV: منتجات وأصناف ورصيد أول المدة</p>
        </div>
        <Link to="/cashier/inventory" className="inline-flex items-center gap-1.5 text-[13px] text-[#7A766C] hover:text-[#E8761A]">
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
          المخزون
        </Link>
      </header>

      <ol className="flex flex-wrap gap-2" aria-label="خطوات الاستيراد">
        {STEPS.map((s, i) => (
          <li
            key={s.key}
            aria-current={i === current ? "step" : undefined}
            className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-[12px] ${i === current ? "border-[#E8761A] bg-[#FDF3EA] font-semibold" : i < current ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-border text-muted-foreground"}`}
          >
            {i < current ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <span>{i + 1}</span>}
            {s.label}
          </li>
        ))}
      </ol>

      {id && query.isPending && <p className="text-[13px] text-muted-foreground">جارٍ التحميل…</p>}
      {loadFailed && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">
          {importErrorText(query.error)}{" "}
          <button type="button" className="underline" onClick={again}>ابدأ استيرادًا جديدًا</button>
        </div>
      )}

      {step === "upload" && !id && <UploadStep busy={upload.isPending} error={error} onFile={onFile} />}
      {session && step === "mapping" && (
        <MappingStep
          session={session}
          draft={mergedMapping(session, draft)}
          policy={policy ?? session.options?.duplicate_policy}
          busy={busy}
          error={error}
          ignored={session.stats?.ignored_sheets ?? []}
          onChange={(sheet, header, field) => setDraft((d) => ({ ...d, [sheet]: assignField(d[sheet] ?? session.sheets[sheet].mapping, header, field) }))}
          onPolicy={(p) => setPolicy(shownPolicy(p))}
          onNext={onCheck}
          onArchive={onArchive}
          archiveBusy={archive.isPending}
          archiveError={error}
        />
      )}
      {session && step === "review" && (
        <ReviewStep session={session} preview={preview.data} busy={busy} error={error} onBack={() => run(() => save.mutateAsync(mappingBody(session, {}, session.options?.duplicate_policy)))} onStart={onStart} onDownload={onDownload} />
      )}
      {session && step === "run" && <RunStep session={session} busy={busy} error={error} onCancel={onCancel} onDownload={onDownload} onAgain={again} />}
    </div>
  );
}
