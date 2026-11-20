import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { Switch } from "@/cashier/components/ui/switch";
import {
  changedValues,
  choiceLabel,
  parseChoice,
  parseNumber,
  parseReasons,
  parseText,
  policyDefinitions,
  policyErrorMessage,
  reasonsToText,
  startingValues,
} from "@/cashier/api/shopPolicy";

// سياسة المحل: المرتجع والاستبدال والخصم. الشاشة تُرسم من تعريفات محرك الإعدادات نفسه، فلا يظهر هنا إلا ما
// يقرأه النظام فعلًا (enforced)، وأي إعداد جديد يُربط بالخادم يظهر وحده. كل حقل يحمل عنوانه ووصفه من المحرك.
// القيم هنا على مستوى المحل كله. الحفظ يرسل ما تغيّر فقط.

function useShopPolicy(domain) {
  const domains = Array.isArray(domain) ? domain : [domain];
  return useQuery({
    queryKey: ["settings", "shop-policy", ...domains],
    staleTime: 0,
    queryFn: async () => {
      // One request pair per domain; the screen shows them as a single form, in the order given.
      const parts = await Promise.all(
        domains.map(async (d) => {
          const [definitions, effective] = await Promise.all([api(`/settings/definitions?domain=${d}`), api(`/settings/effective?domain=${d}`)]);
          return { defs: policyDefinitions(definitions, { domain: d }), effective };
        }),
      );
      return {
        defs: parts.flatMap((p) => p.defs),
        effective: Object.assign({}, ...parts.map((p) => p.effective)),
      };
    },
  });
}

export function Field({ def, value, text, error, onChange }) {
  const label = def.label_ar || def.label_en || def.key;
  const desc = def.description_ar || def.description_en;
  let control;
  if (def.type === "bool") {
    // This tab lives on the general settings page, outside .cashier-root, where --primary and --input do not exist:
    // the switch would be transparent whether on or off. Explicit colours keep on/off readable.
    control = (
      <Switch
        checked={Boolean(value)}
        onCheckedChange={(v) => onChange(v)}
        aria-label={label}
        className="data-[state=checked]:!bg-[#E8761A] data-[state=unchecked]:!bg-slate-300"
      />
    );
  } else if (def.type === "list") {
    control = (
      <textarea
        value={text}
        onChange={(e) => onChange(e.target.value)}
        rows={4}
        aria-label={label}
        placeholder="سبب في كل سطر (مثل: size, defect, changed_mind, wrong_item)"
        className="w-full min-w-[220px] rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px]"
      />
    );
  } else if (def.type === "enum") {
    control = (
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className="h-8 min-w-[160px] rounded-md border border-border bg-background px-2 text-[13px]"
      >
        {(def.allowed_values ?? []).map((v) => (
          <option key={v} value={v}>
            {choiceLabel(def, v)}
          </option>
        ))}
      </select>
    );
  } else if (def.type === "string") {
    control = (
      <input
        type="text"
        dir="auto"
        value={text}
        maxLength={def.max_length ?? undefined}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className="h-8 w-56 rounded-md border border-border bg-background px-2 text-[13px]"
      />
    );
  } else if (def.type === "number") {
    control = (
      <input
        type="text"
        inputMode="decimal"
        placeholder={def.default === null ? "بدون حد" : undefined}
        value={text}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className="num h-8 w-28 rounded-md border border-border bg-background px-2 text-[13px]"
      />
    );
  } else {
    // A kind of setting this screen cannot edit: say so, never draw a wrong control for it.
    control = <span className="text-[12px] text-muted-foreground">لا يمكن تعديله من هنا</span>;
  }
  return (
    <div className="flex flex-col gap-1.5 border-b border-border py-3 last:border-b-0 sm:flex-row sm:items-start sm:justify-between sm:gap-6" data-testid={`policy-${def.key}`}>
      <div className="min-w-0">
        <p className="text-[13px] font-semibold">{label}</p>
        {desc && <p className="mt-0.5 text-[12px] text-muted-foreground">{desc}</p>}
        {error && <p role="alert" className="mt-1 text-[12px] font-medium text-rose-600">{error}</p>}
      </div>
      <div className="shrink-0 max-sm:w-full">{control}</div>
    </div>
  );
}

export default function ShopPolicySettings({
  domain = "pos",
  title = "سياسة المحل",
  description = "المرتجع والاستبدال والخصم. كل ما تضبطه هنا يطبّقه الكاشير والنظام فعلًا.",
}) {
  const qc = useQueryClient();
  const QUERY = ["settings", "shop-policy", ...(Array.isArray(domain) ? domain : [domain])];
  const { data, isLoading, error: loadError } = useShopPolicy(domain);
  const [draft, setDraft] = useState(null); // what the form holds: numbers/bools as values, lists as text
  const [saving, setSaving] = useState(false);

  const original = useMemo(() => (data ? startingValues(data.defs, data.effective) : null), [data]);
  useEffect(() => {
    if (!data || !original) return;
    setDraft(Object.fromEntries(data.defs.map((d) => [d.key, d.type === "list" ? reasonsToText(original[d.key]) : d.type === "number" ? String(original[d.key] ?? "") : original[d.key]])));
  }, [data, original]);

  // The draft in the shape the server stores, with each field's own problem if it has one.
  const parsed = useMemo(() => {
    if (!data || !draft) return null;
    const values = {};
    const errors = {};
    for (const d of data.defs) {
      if (d.type === "number") {
        const r = parseNumber(d, draft[d.key]);
        if (r.error) errors[d.key] = r.error;
        else values[d.key] = r.value;
      } else if (d.type === "list") {
        values[d.key] = parseReasons(draft[d.key]);
      } else if (d.type === "string") {
        const r = parseText(d, draft[d.key]);
        if (r.error) errors[d.key] = r.error;
        else values[d.key] = r.value;
      } else if (d.type === "enum") {
        const r = parseChoice(d, draft[d.key]);
        if (r.error) errors[d.key] = r.error;
        else values[d.key] = r.value;
      } else {
        values[d.key] = draft[d.key];
      }
    }
    return { values, errors };
  }, [data, draft]);

  const changes = parsed && data ? changedValues(data.defs, original, parsed.values) : [];
  const hasErrors = parsed ? Object.keys(parsed.errors).length > 0 : false;

  async function save() {
    if (!changes.length || hasErrors || saving) return;
    setSaving(true);
    try {
      await api("/settings/bulk", { method: "POST", body: { scope: "tenant", settings: Object.fromEntries(changes.map((c) => [c.key, c.value])) } });
      // Everything that read these values starts again from the server, so the till picks them up too.
      await Promise.all([qc.invalidateQueries({ queryKey: QUERY }), qc.invalidateQueries({ queryKey: ["cashier", "return-policy"] })]);
      toast.success(changes.length === 1 ? "تم حفظ التعديل" : `تم حفظ ${changes.length} تعديلات`);
    } catch (e) {
      toast.error(policyErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  if (isLoading || !draft) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        جارٍ التحميل…
      </div>
    );
  }
  if (loadError) {
    return <p role="alert" className="py-6 text-[13px] text-rose-600">{policyErrorMessage(loadError)}</p>;
  }

  return (
    <SectionCard
      flat
      title={title}
      description={description}
      action={
        <button
          type="button"
          onClick={save}
          disabled={!changes.length || hasErrors || saving}
          className="h-8 rounded-lg bg-[#E8761A] px-4 text-[12.5px] font-semibold text-white disabled:opacity-40"
        >
          {saving ? "جارٍ الحفظ…" : "حفظ"}
        </button>
      }
    >
      {data.defs.map((d) => (
        <Field key={d.key} def={d} value={draft[d.key]} text={draft[d.key] ?? ""} error={parsed.errors[d.key]} onChange={(v) => setDraft((p) => ({ ...p, [d.key]: v }))} />
      ))}
    </SectionCard>
  );
}
