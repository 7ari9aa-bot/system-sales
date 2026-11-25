import React from "react";
import { Save } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SectionCard } from "@/components/dashboard/ui";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";

/** Organization & branch settings card — reads and writes organization.* and branch.* via the settings API.
 *
 * Shown on the Workspace settings page so the owner can toggle multi-branch, set the branch
 * limit, default language, and branch operational settings (auto-close, shift end, etc).
 */
export default function OrganizationBranchCard() {
  const { lang } = useI18n();
  const isAr = lang === "ar";

  const [defs, setDefs] = React.useState(null);
  const [values, setValues] = React.useState({});
  const [original, setOriginal] = React.useState({});
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    Promise.all([
      api("/settings/definitions?domain=organization"),
      api("/settings/definitions?domain=branch"),
      api("/settings/effective?domain=organization"),
      api("/settings/effective?domain=branch"),
    ])
      .then(([orgDefs, branchDefs, orgEff, branchEff]) => {
        if (!alive) return;
        setDefs([...(orgDefs || []), ...(branchDefs || [])]);
        const v = {};
        for (const [key, resolved] of Object.entries(orgEff || {})) v[key] = resolved.value;
        for (const [key, resolved] of Object.entries(branchEff || {})) v[key] = resolved.value;
        setValues(v);
        setOriginal(v);
      })
      .catch((err) => {
        if (alive) setError(err?.message || (isAr ? "تعذر تحميل الإعدادات" : "Could not load settings"));
      });
    return () => { alive = false; };
  }, [isAr]);

  const dirty = JSON.stringify(values) !== JSON.stringify(original);

  async function save() {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const changes = {};
      for (const [k, v] of Object.entries(values)) {
        if (v !== original[k]) changes[k] = v;
      }
      if (Object.keys(changes).length > 0) {
        await api("/settings/bulk", {
          method: "POST",
          body: { scope: "tenant", settings: changes },
        });
      }
      setOriginal({ ...values });
      setNotice(isAr ? "تم الحفظ" : "Saved");
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر الحفظ" : "Could not save"));
    } finally {
      setSaving(false);
    }
  }

  if (!defs) {
    return (
      <SectionCard title={isAr ? "إعدادات المؤسسة والفروع" : "Organization & Branch Settings"}>
        <div className="py-4 text-[13px] text-muted-foreground">
          {error || (isAr ? "جارٍ التحميل…" : "Loading…")}
        </div>
      </SectionCard>
    );
  }

  const defMap = {};
  for (const d of defs) defMap[d.key] = d;

  const boolKeys = [
    "organization.multi_branch",
    "branch.auto_close_shift",
    "branch.notify_manager_on_variance",
    "branch.allow_independent_purchasing",
  ];
  const selectKeys = {
    "organization.default_language": ["ar", "en"],
  };
  const numberKeys = ["organization.max_branches"];
  const stringKeys = ["branch.shift_end_time"];

  return (
    <SectionCard title={isAr ? "إعدادات المؤسسة والفروع" : "Organization & Branch Settings"}>
      {error && <div role="alert" className="mb-3 text-[12px] text-destructive">{error}</div>}
      {notice && <div className="mb-3 text-[12px] text-success">{notice}</div>}

      {defs.map((d) => {
        const key = d.key;
        const label = d.label?.[lang] || key;
        const desc = d.description?.[lang];

        if (boolKeys.includes(key)) {
          return (
            <div key={key} className="flex items-center justify-between py-2.5 border-b border-border">
              <div>
                <div className="text-[13px] font-medium">{label}</div>
                {desc && <div className="text-[12px] text-muted-foreground mt-0.5">{desc}</div>}
              </div>
              <Switch
                checked={values[key] === true || values[key] === "true"}
                onCheckedChange={(v) => setValues((s) => ({ ...s, [key]: v }))}
              />
            </div>
          );
        }

        if (selectKeys[key]) {
          return (
            <div key={key} className="flex items-center justify-between py-2.5 border-b border-border">
              <div>
                <div className="text-[13px] font-medium">{label}</div>
                {desc && <div className="text-[12px] text-muted-foreground mt-0.5">{desc}</div>}
              </div>
              <Select
                value={values[key] || "ar"}
                onValueChange={(v) => setValues((s) => ({ ...s, [key]: v }))}
              >
                <SelectTrigger className="w-[100px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {selectKeys[key].map((v) => (
                    <SelectItem key={v} value={v}>{v === "ar" ? "العربية" : "English"}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          );
        }

        if (numberKeys.includes(key)) {
          return (
            <div key={key} className="flex items-center justify-between py-2.5 border-b border-border">
              <div>
                <div className="text-[13px] font-medium">{label}</div>
                {desc && <div className="text-[12px] text-muted-foreground mt-0.5">{desc}</div>}
              </div>
              <Input
                type="number"
                className="w-[80px]"
                value={values[key] ?? 0}
                onChange={(e) => setValues((s) => ({ ...s, [key]: parseInt(e.target.value) || 0 }))}
              />
            </div>
          );
        }

        if (stringKeys.includes(key)) {
          return (
            <div key={key} className="flex items-center justify-between py-2.5 border-b border-border">
              <div>
                <div className="text-[13px] font-medium">{label}</div>
                {desc && <div className="text-[12px] text-muted-foreground mt-0.5">{desc}</div>}
              </div>
              <Input
                className="w-[80px]"
                placeholder="HH:MM"
                value={values[key] || "23:59"}
                onChange={(e) => setValues((s) => ({ ...s, [key]: e.target.value }))}
              />
            </div>
          );
        }

        return null;
      })}

      {dirty && (
        <div className="pt-3">
          <Button onClick={save} disabled={saving} className="h-8 text-[12px]">
            <Save className="h-3.5 w-3.5 mr-1.5" />
            {saving ? "…" : (isAr ? "حفظ" : "Save")}
          </Button>
        </div>
      )}
    </SectionCard>
  );
}
