import React from "react";
import { Save } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { activeTenantId } from "@/lib/activeTenant";
import { useAuth } from "@/lib/AuthContext";
import { SectionCard } from "@/components/dashboard/ui";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { AUTO, dialectBody, dialectOptions, isDirty, selectionFrom, sourceKey } from "@/pages/settings/dialectSetting";

/** How the assistant talks to the owner: the dialect setting.
 *
 * It belongs to the AI screen, not to the profile: it is the assistant's behaviour, not a fact
 * about the person. It also keeps its OWN save button, so changing the shop's country can never
 * silently rewrite how the assistant speaks — those are two different decisions.
 *
 * The server owns the list of dialects and says what is now in use; this card shows that answer
 * instead of echoing the pick, and "Automatic" is sent as an explicit null (clear my choice).
 */
export default function DialectCard() {
  const t = useT();
  const { user } = useAuth();
  const tenantId = activeTenantId(user);
  const [info, setInfo] = React.useState(null);
  const [choice, setChoice] = React.useState(AUTO);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  React.useEffect(() => {
    if (!tenantId) return undefined;
    let alive = true;
    api(`/tenants/${tenantId}/dialect`)
      .then((loaded) => {
        if (!alive) return;
        setInfo(loaded);
        setChoice(selectionFrom(loaded));
      })
      .catch((failure) => {
        if (alive) setError(failure?.message || t("dialect.loadFailed"));
      });
    return () => {
      alive = false;
    };
  }, [tenantId, t]);

  async function save() {
    if (!tenantId || !info) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = await api(`/tenants/${tenantId}/dialect`, {
        method: "PUT",
        body: dialectBody(choice, info.choices),
      });
      // what the SERVER says is in use now, not what was picked
      setInfo(saved);
      setChoice(selectionFrom(saved));
      setNotice(t("dialect.saved"));
    } catch (failure) {
      setError(failure?.message || t("dialect.saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <SectionCard title={t("dialect.title")} className="rounded-none border-0 bg-transparent" bodyClassName="px-0 pt-2" headerClassName="px-0 pt-0">
      <p className="text-[12.5px] leading-relaxed text-muted-foreground">{t("dialect.desc")}</p>
      <div className="mt-2 flex flex-col gap-2 border-t border-border pt-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="text-[13.5px] font-medium">{t("dialect.label")}</div>
          {info && (
            <div className="mt-0.5 text-[12px] text-muted-foreground">
              {`${t("dialect.using")}: ${t(`dialect.name.${info.effective}`)} (${t(sourceKey(info))})`}
            </div>
          )}
        </div>
        <Select value={choice} onValueChange={setChoice} disabled={!info}>
          <SelectTrigger className="w-[220px]" data-testid="dialect-select">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {dialectOptions(info).map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.value === AUTO ? t("dialect.auto") : t(`dialect.name.${option.value}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {(error || notice) && (
        <div
          role={error ? "alert" : "status"}
          data-testid="dialect-message"
          className={`mt-3 rounded-lg px-3 py-2 text-[12px] ${error ? "bg-destructive/10 text-destructive" : "bg-success/10 text-foreground"}`}
        >
          {error || notice}
        </div>
      )}
      <div className="mt-3 flex justify-end">
        <Button
          type="button"
          data-testid="dialect-save"
          onClick={save}
          disabled={!isDirty(choice, info) || saving}
          className="gap-1.5"
        >
          <Save className="h-4 w-4" />
          {saving ? "…" : t("businessProfile.save")}
        </Button>
      </div>
    </SectionCard>
  );
}
