import React from "react";
import { Save } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SectionCard } from "@/components/dashboard/ui";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

/** The two payloads this card needs, made safe.
 *
 * `/settings/definitions` answers with a list and `/settings/effective` with a keyed object.
 * A payload that is neither (an error envelope the client did not raise on, a proxy page, a
 * shape change on the server) used to throw inside the render pass and take the whole AI
 * screen down with a white error page — the dialect card below it became unreachable even
 * though it had loaded fine. Coercing here keeps one bad response to this card.
 */
export function normalizeSettingsPayload(definitions, effective) {
  const defs = Array.isArray(definitions) ? definitions : [];
  const values = {};
  for (const [key, resolved] of Object.entries(effective && typeof effective === "object" ? effective : {})) {
    values[key] = resolved?.value;
  }
  return { defs, values };
}

/** Analytics agent settings card — reads and writes analytics_agent.* via the settings API.
 *
 * Shown on the AI page so the owner can toggle the agent, set the default report period,
 * and adjust the minimum confidence threshold.
 */
export default function AnalyticsAgentCard() {
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
      api("/settings/definitions?domain=analytics_agent"),
      api("/settings/effective?domain=analytics_agent"),
    ])
      .then(([d, eff]) => {
        if (!alive) return;
        const { defs: safeDefs, values: loaded } = normalizeSettingsPayload(d, eff);
        setDefs(safeDefs);
        setValues(loaded);
        setOriginal(loaded);
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
      <SectionCard title={isAr ? "إعدادات وكيل التحليلات" : "Analytics Agent Settings"}>
        <div className="py-4 text-[13px] text-muted-foreground">
          {error || (isAr ? "جارٍ التحميل…" : "Loading…")}
        </div>
      </SectionCard>
    );
  }

  const defMap = {};
  for (const d of defs) defMap[d.key] = d;

  return (
    <SectionCard title={isAr ? "إعدادات وكيل التحليلات" : "Analytics Agent Settings"}>
      {error && <div role="alert" className="mb-3 text-[12px] text-destructive">{error}</div>}
      {notice && <div className="mb-3 text-[12px] text-success">{notice}</div>}

      {/* Enabled toggle */}
      {defMap["analytics_agent.enabled"] && (
        <div className="flex items-center justify-between py-2.5 border-b border-border">
          <div>
            <div className="text-[13px] font-medium">
              {defMap["analytics_agent.enabled"].label?.[lang] || (isAr ? "تفعيل وكيل التحليلات" : "Analytics Agent Enabled")}
            </div>
            <div className="text-[12px] text-muted-foreground mt-0.5">
              {defMap["analytics_agent.enabled"].description?.[lang]}
            </div>
          </div>
          <Switch
            checked={values["analytics_agent.enabled"] === true || values["analytics_agent.enabled"] === "true"}
            onCheckedChange={(v) => setValues((s) => ({ ...s, "analytics_agent.enabled": v }))}
          />
        </div>
      )}

      {/* Default period */}
      {defMap["analytics_agent.default_period"] && (
        <div className="flex items-center justify-between py-2.5 border-b border-border">
          <div>
            <div className="text-[13px] font-medium">
              {defMap["analytics_agent.default_period"].label?.[lang] || (isAr ? "الفترة الافتراضية" : "Default Period")}
            </div>
            <div className="text-[12px] text-muted-foreground mt-0.5">
              {defMap["analytics_agent.default_period"].description?.[lang]}
            </div>
          </div>
          <Select
            value={values["analytics_agent.default_period"] || "30d"}
            onValueChange={(v) => setValues((s) => ({ ...s, "analytics_agent.default_period": v }))}
          >
            <SelectTrigger className="w-[100px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {(defMap["analytics_agent.default_period"].allowed_values || ["7d", "30d", "90d", "ytd", "all"]).map((v) => (
                <SelectItem key={v} value={v}>{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Min confidence */}
      {defMap["analytics_agent.min_confidence"] && (
        <div className="flex items-center justify-between py-2.5 border-b border-border">
          <div>
            <div className="text-[13px] font-medium">
              {defMap["analytics_agent.min_confidence"].label?.[lang] || (isAr ? "الحد الأدنى للثقة" : "Minimum Confidence")}
            </div>
            <div className="text-[12px] text-muted-foreground mt-0.5">
              {defMap["analytics_agent.min_confidence"].description?.[lang]}
            </div>
          </div>
          <Select
            value={String(values["analytics_agent.min_confidence"] ?? "0.7")}
            onValueChange={(v) => setValues((s) => ({ ...s, "analytics_agent.min_confidence": parseFloat(v) }))}
          >
            <SelectTrigger className="w-[100px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="0.5">0.5</SelectItem>
              <SelectItem value="0.7">0.7</SelectItem>
              <SelectItem value="0.8">0.8</SelectItem>
              <SelectItem value="0.9">0.9</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

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
