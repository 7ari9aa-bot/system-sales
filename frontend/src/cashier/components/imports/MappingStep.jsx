import { AlertTriangle, ArrowLeft, Loader2 } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { SHEET_LABEL, canValidate, ignoredColumnsOf, mappingRows } from "@/cashier/api/importCenter";

const IGNORE = "__ignore__";

/** What to do with a product or SKU the shop already has. `create_only` and `skip` behave the same, so one is offered. */
export const DUPLICATE_CHOICES = [
  { value: "skip", label: "تخطّي الموجود", hint: "لا يتغيّر أي منتج أو صنف موجود في متجرك" },
  { value: "update", label: "تحديث الموجود", hint: "تُحدَّث بيانات المنتج أو الصنف الموجود من الملف" },
];

/** The policy the screen shows: the server's default `create_only` is the same as skipping. */
export const shownPolicy = (value) => (value === "update" ? "update" : "skip");

function SheetMapping({ name, sheet, onChange }) {
  const rows = mappingRows(sheet);
  const missing = sheet.missing_required ?? [];
  const labelOf = (key) => sheet.fields.find((f) => f.key === key)?.label_ar ?? key;
  // Only columns still unmapped on screen: a merchant who maps one by hand clears the warning.
  const stillIgnored = new Set(rows.filter((r) => !r.field).map((r) => r.header));
  const ignoredNow = ignoredColumnsOf({
    ignored_columns: (sheet.ignored_columns ?? []).filter((c) => stillIgnored.has(c.column)),
  });
  return (
    <SectionCard
      title={SHEET_LABEL[name] ?? name}
      description={`${sheet.rows} صفًّا`}
      action={missing.length > 0 && <span className="text-[11px] font-semibold text-red-600">ناقص: {missing.map(labelOf).join("، ")}</span>}
    >
      {ignoredNow.stock.length > 0 && (
        <p role="alert" className="mb-2 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            العمود {ignoredNow.stock.map((c) => `«${c}»`).join("، ")} لن يُحمَّل كرصيد. الكميات تُستورد فقط من ورقة <b>رصيد أول المدة</b> (أعمدتها: SKU والكمية والمخزن).
          </span>
        </p>
      )}
      <ul className="divide-y divide-border">
        {rows.map(({ header, field }) => (
          <li key={header} className="flex items-center gap-3 py-2">
            <span className="min-w-0 flex-1 truncate text-[13px]" title={header}>{header}</span>
            <ArrowLeft className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <Select value={field || IGNORE} onValueChange={(v) => onChange(name, header, v === IGNORE ? "" : v)}>
              <SelectTrigger className="h-9 w-48 text-[12px]" aria-label={`حقل العمود ${header}`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent dir="rtl">
                <SelectItem value={IGNORE}>تجاهل هذا العمود</SelectItem>
                {sheet.fields.map((f) => (
                  <SelectItem key={f.key} value={f.key}>
                    {f.label_ar}
                    {f.required ? " *" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

/** Step 2: which column is which. Nothing here is saved until the merchant moves on. */
export default function MappingStep({ session, draft, policy, busy, error, ignored, onChange, onPolicy, onNext }) {
  const view = { ...session, sheets: Object.fromEntries(Object.entries(session.sheets).map(([k, s]) => [k, { ...s, mapping: draft[k] ?? s.mapping }])) };
  return (
    <div className="flex flex-col gap-4">
      {ignored.length > 0 && (
        <p className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          أوراق لم تُقرأ لأن اسمها غير معروف: {ignored.join("، ")}
        </p>
      )}
      {Object.entries(view.sheets).map(([name, sheet]) => (
        <SheetMapping key={name} name={name} sheet={sheet} onChange={onChange} />
      ))}
      <SectionCard title="لو المنتج موجود عندك بالفعل" description="يُحدَّد الموجود بالـ SKU أو معرّف المنتج">
        <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="التعامل مع الموجود">
          {DUPLICATE_CHOICES.map((c) => (
            <label key={c.value} className={`cursor-pointer rounded-lg border px-3 py-2.5 text-[13px] ${shownPolicy(policy) === c.value ? "border-[#E8761A] bg-[#FDF3EA]" : "border-border"}`}>
              <input type="radio" name="duplicate_policy" className="sr-only" checked={shownPolicy(policy) === c.value} onChange={() => onPolicy(c.value)} />
              <span className="block font-semibold">{c.label}</span>
              <span className="block text-[11px] text-muted-foreground">{c.hint}</span>
            </label>
          ))}
        </div>
      </SectionCard>
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">{error}</p>}
      <div className="flex justify-end">
        <Button type="button" onClick={onNext} disabled={busy || !canValidate(view)} className="gap-2 bg-[#E8761A] text-white hover:bg-[#D1650F]">
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
          فحص الملف
        </Button>
      </div>
    </div>
  );
}
