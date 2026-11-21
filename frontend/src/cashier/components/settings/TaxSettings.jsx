import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Loader2, PauseCircle } from "lucide-react";
import { api } from "@/lib/api";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { Switch } from "@/cashier/components/ui/switch";
import { cn } from "@/cashier/lib/utils";
import { changedValues, parseChoice, parseText, policyErrorMessage, startingValues } from "@/cashier/api/shopPolicy";
import { FRIENDLY, SECTIONS, TAX_DOMAINS, readiness, sectionDefs } from "@/cashier/api/taxSettings";
import { Field, useShopPolicy } from "./ShopPolicySettings";

// تبويب الضرائب: لوحة حالة بتقول الإيصال الإلكتروني شغال ولا واقف وليه، وبعدها الإعدادات في أقسام
// بالترتيب اللي التاجر بيملّيه بيه. نفس الجلب والحفظ بتوع باقي إعدادات المحل (/settings/bulk).

const PANEL = {
  running: { Icon: CheckCircle2, cls: "border-emerald-200 bg-emerald-50 text-emerald-800", title: "الإيصال الإلكتروني شغال", body: "كل بيع ومرتجع من الكاشير بيتحوّل لإيصال إلكتروني." },
  blocked: { Icon: AlertTriangle, cls: "border-amber-300 bg-amber-50 text-amber-900", title: "الإيصال الإلكتروني متفعّل لكنه واقف" },
  off: { Icon: PauseCircle, cls: "border-border bg-muted/40 text-muted-foreground", title: "الإيصال الإلكتروني مقفول", body: "فعّله لما تكون جاهز. مفيش حاجة هتتبعت للمصلحة وهو مقفول." },
};

/** The panel only draws what `readiness` decided. Exported so it can be tested without a server. */
export function StatusPanel({ status, enabled, confirmed, onEnabled, onConfirmed }) {
  const p = PANEL[status.state];
  return (
    <div className={cn("rounded-xl border p-3", p.cls)} data-state={status.state} data-testid="tax-status">
      <div className="flex items-start gap-2">
        <p.Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-[14px] font-bold">{p.title}</p>
          {p.body && <p className="mt-0.5 text-[12.5px]">{p.body}</p>}
          {status.reasons?.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pe-4 text-[12.5px]">
              {status.reasons.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
        </div>
      </div>
      <div className="mt-3 flex flex-col gap-2 border-t border-black/10 pt-3">
        <label className="flex items-center justify-between gap-3 text-[13px] font-semibold">
          <span>تفعيل الإيصال الإلكتروني</span>
          <Switch checked={Boolean(enabled)} onCheckedChange={onEnabled} aria-label="تفعيل الإيصال الإلكتروني" className="data-[state=checked]:!bg-[#E8761A] data-[state=unchecked]:!bg-slate-300" />
        </label>
        <label className="flex items-center justify-between gap-3 text-[13px] font-semibold">
          <span>راجعت الأسعار والضريبة وطريقة الدفع وأكّدتها</span>
          <Switch checked={Boolean(confirmed)} onCheckedChange={onConfirmed} aria-label="أكّدت إعدادات الأسعار والضريبة والدفع" className="data-[state=checked]:!bg-[#E8761A] data-[state=unchecked]:!bg-slate-300" />
        </label>
        <p className="text-[11.5px] opacity-80">القيم الأولية اقتراحات مش حقائق: كل محل بيختلف. راجعها في الأقسام تحت قبل ما تأكّد.</p>
      </div>
    </div>
  );
}

const friendly = (d) => (FRIENDLY[d.key] ? { ...d, label_ar: FRIENDLY[d.key].label, description_ar: FRIENDLY[d.key].description } : d);

export default function TaxSettings() {
  const qc = useQueryClient();
  const { data, isLoading, error: loadError } = useShopPolicy(TAX_DOMAINS);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);

  const original = useMemo(() => (data ? startingValues(data.defs, data.effective) : null), [data]);
  useEffect(() => {
    if (original) setDraft({ ...original });
  }, [original]);

  // What would be saved: text kept as text, a choice only from the server's own list.
  const errors = useMemo(() => {
    const e = {};
    for (const d of data?.defs ?? []) {
      if (!draft) break;
      const r = d.type === "string" ? parseText(d, draft[d.key]) : d.type === "enum" ? parseChoice(d, draft[d.key]) : {};
      if (r.error) e[d.key] = r.error;
    }
    return e;
  }, [data, draft]);

  const changes = data && draft && original ? changedValues(data.defs, original, draft) : [];
  const status = useMemo(() => readiness(draft ?? {}), [draft]);

  async function save() {
    if (!changes.length || Object.keys(errors).length || saving) return;
    setSaving(true);
    try {
      await api("/settings/bulk", { method: "POST", body: { scope: "tenant", settings: Object.fromEntries(changes.map((c) => [c.key, c.value])) } });
      await qc.invalidateQueries({ queryKey: ["settings", "shop-policy"] });
      toast.success(changes.length === 1 ? "تم حفظ التعديل" : `تم حفظ ${changes.length} تعديلات`);
    } catch (e) {
      toast.error(policyErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  if (loadError) return <p role="alert" className="py-6 text-[13px] text-rose-600">{policyErrorMessage(loadError)}</p>;
  if (isLoading || !draft) {
    return <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground" role="status"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> جارٍ التحميل…</div>;
  }
  const set = (key) => (v) => setDraft((p) => ({ ...p, [key]: v }));

  return (
    <div className="space-y-3" dir="rtl">
      <StatusPanel status={status} enabled={draft["einvoice.eta_enabled"]} confirmed={draft["einvoice.settings_confirmed"]} onEnabled={set("einvoice.eta_enabled")} onConfirmed={set("einvoice.settings_confirmed")} />
      {SECTIONS.map((s) => {
        const defs = sectionDefs(s, data.defs);
        if (!defs.length) return null;
        return (
          <SectionCard key={s.id} flat={false} title={s.title} description={s.hint}>
            {defs.map((d) => (
              <Field key={d.key} def={friendly(d)} value={draft[d.key]} text={draft[d.key] ?? ""} error={errors[d.key]} onChange={set(d.key)} />
            ))}
          </SectionCard>
        );
      })}
      <div className="sticky bottom-2 flex justify-end">
        <button type="button" onClick={save} disabled={!changes.length || Object.keys(errors).length > 0 || saving} className="h-9 rounded-lg bg-[#E8761A] px-6 text-[13px] font-semibold text-white shadow disabled:opacity-40">
          {saving ? "جارٍ الحفظ…" : changes.length ? `حفظ (${changes.length})` : "حفظ"}
        </button>
      </div>
    </div>
  );
}
