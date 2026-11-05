import React from "react";
import { Loader2, Save } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/AuthContext";
import { useI18n } from "@/lib/i18n";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const emptyDraft = {
  name: "", deposit_type: "", deposit_value: "", calculation_base: "grand_total",
  minimum_deposit: "", maximum_deposit: "",
};
const types = ["none", "percentage", "fixed"];
const bases = ["grand_total", "items_after_discounts"];
const MAX_NAME_CHARS = 127;
// The application's cap on typed money, not the column's capacity.
const MAX_MONEY_UNITS = 99999999999n;

function toDraft(policy) {
  if (!policy) return { ...emptyDraft };
  return Object.fromEntries(Object.keys(emptyDraft).map((key) => [key, policy[key] ?? ""]));
}

/** A rule written in another currency is not re-labelled: its absolute money is
 * dropped so the merchant re-enters it in the currency the shop trades in now. */
function dropForeignMoney(draft) {
  if (draft.deposit_type === "fixed") return { ...draft, deposit_value: "", minimum_deposit: "", maximum_deposit: "" };
  return { ...draft, minimum_deposit: "", maximum_deposit: "" };
}

function validDecimal(value) {
  return /^\d+(\.\d{1,2})?$/.test(value) && Number.isFinite(Number(value));
}

function moneyUnits(value) {
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole + fraction.padEnd(2, "0"));
}

function validationKey(draft) {
  const name = draft.name.trim();
  if (!name) return "nameRequired";
  if (name.length > MAX_NAME_CHARS) return "nameTooLong";
  if (!types.includes(draft.deposit_type)) return "typeRequired";
  if (draft.deposit_type === "none") return null;
  if (!validDecimal(draft.deposit_value) || Number(draft.deposit_value) <= 0) return "valueInvalid";
  if (draft.deposit_type === "percentage" && Number(draft.deposit_value) > 100) return "percentageInvalid";
  const money = draft.deposit_type === "percentage"
    ? [draft.minimum_deposit, draft.maximum_deposit]
    : [draft.deposit_value, draft.minimum_deposit, draft.maximum_deposit];
  for (const value of [draft.minimum_deposit, draft.maximum_deposit]) {
    if (value !== "" && !validDecimal(value)) return "bandInvalid";
  }
  if (money.some((value) => value !== "" && moneyUnits(value) > MAX_MONEY_UNITS)) return "amountTooLarge";
  if (draft.minimum_deposit !== "" && draft.maximum_deposit !== "" &&
    moneyUnits(draft.minimum_deposit) > moneyUnits(draft.maximum_deposit)) return "bandOrder";
  return null;
}

/** The server's own message is not shown: a refusal that is not on this list
 * could carry internals. Every case the merchant can act on is validated here. */
function errorKey(error) {
  if (error?.status === 401 || error?.status === 403) return "saveForbidden";
  if (error?.retryable) return "saveRetry";
  if (error?.status === 400 || error?.status === 422 || error?.code === "validation_error") return "saveInvalid";
  return "saveFailed";
}

export default function DepositPolicySettings() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  // auth/me answers with the tenant LIST and never a currency; the shop's money
  // is its own setting, so the labels come from that route or not at all.
  const tenantId = user?.tenants?.length === 1 ? user.tenants[0].id : null;
  const [policies, setPolicies] = React.useState([]);
  const [currency, setCurrency] = React.useState(null);
  const [draft, setDraft] = React.useState(emptyDraft);
  const [baseline, setBaseline] = React.useState(emptyDraft);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState(null);
  const [attempt, setAttempt] = React.useState(0);
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState(null);
  const [saved, setSaved] = React.useState(false);
  const [acknowledged, setAcknowledged] = React.useState(false);

  React.useEffect(() => {
    // More than one workspace in the session and no server-side answer for the
    // active one: guessing would label money with the wrong currency.
    if (!tenantId) {
      setLoading(false);
      setLoadError({ key: "currencyMissing", retryable: false });
      return undefined;
    }
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    Promise.all([
      api("/orders/deposit-policies", { signal: controller.signal }),
      api(`/tenants/${tenantId}/currency`, { signal: controller.signal }),
    ])
      .then(([items, tenant]) => {
        if (controller.signal.aborted) return;
        const code = tenant?.currency || null;
        const active = items.find((policy) => policy.is_active);
        const initial = active && code && active.currency !== code
          ? dropForeignMoney(toDraft(active))
          : toDraft(active);
        setPolicies(items);
        setCurrency(code);
        setDraft(initial);
        setBaseline(initial);
        if (!code) setLoadError({ key: "currencyMissing", retryable: false });
      })
      .catch((error) => {
        if (error.name === "AbortError") return;
        const forbidden = error?.status === 401 || error?.status === 403;
        setLoadError({ key: forbidden ? "loadForbidden" : "loadError", retryable: Boolean(error?.retryable) });
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt, tenantId]);

  const active = policies.find((policy) => policy.is_active);
  const mismatch = Boolean(active && currency && active.currency !== currency);
  const needsAck = mismatch && draft.deposit_type !== "none";
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  const validation = validationKey(draft);
  const hasValue = draft.deposit_type && draft.deposit_type !== "none";
  const update = (key, value) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setSaved(false);
  };

  async function save(event) {
    event.preventDefault();
    if (saving || validation || needsAck !== acknowledged || (!dirty && !mismatch)) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const policy = await api("/orders/deposit-policies", {
        method: "POST",
        body: {
          name: draft.name.trim(),
          deposit_type: draft.deposit_type,
          deposit_value: hasValue ? draft.deposit_value : "0",
          calculation_base: draft.deposit_type === "percentage" ? draft.calculation_base : "grand_total",
          minimum_deposit: hasValue && draft.minimum_deposit !== "" ? draft.minimum_deposit : null,
          maximum_deposit: hasValue && draft.maximum_deposit !== "" ? draft.maximum_deposit : null,
        },
      });
      const nextDraft = toDraft(policy);
      setPolicies((current) => [policy, ...current.filter((item) => item.id !== policy.id)
        .map((item) => policy.is_active ? { ...item, is_active: false } : item)]);
      setDraft(nextDraft);
      setBaseline(nextDraft);
      setAcknowledged(false);
      setSaved(true);
    } catch (error) {
      setSaveError(errorKey(error));
    } finally {
      setSaving(false);
    }
  }

  function select(key, options) {
    return (
      <div className="min-w-0 space-y-2">
        <Label htmlFor={`deposit-${key}`}>{t(`deposit.${key}`)}</Label>
        <Select value={draft[key]} onValueChange={(value) => update(key, value)} disabled={saving} dir={lang === "ar" ? "rtl" : "ltr"}>
          <SelectTrigger id={`deposit-${key}`}><SelectValue placeholder={t("deposit.chooseType")} /></SelectTrigger>
          <SelectContent>{options.map((option) => <SelectItem key={option} value={option}>{t(`deposit.${option}`)}</SelectItem>)}</SelectContent>
        </Select>
      </div>
    );
  }

  function input(key, label, numeric = false) {
    return (
      <div className="min-w-0 space-y-2">
        <Label htmlFor={`deposit-${key}`}>{label}</Label>
        <Input id={`deposit-${key}`} value={draft[key]} onChange={(event) => update(key, event.target.value)}
          dir={numeric ? "ltr" : "auto"} inputMode={numeric ? "decimal" : undefined}
          aria-describedby={numeric ? "deposit-number-help" : undefined} />
      </div>
    );
  }

  return (
    <div role="region" aria-label={t("deposit.title")}>
      <SettingCard title={t("deposit.title")} desc={t("deposit.desc")}>
        <p className="my-4 rounded-lg border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
          {t("deposit.notice")}
        </p>
        {loading ? (
          <p role="status" className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />{t("deposit.loading")}
          </p>
        ) : loadError ? (
          <div className="space-y-3">
            <p role="alert" className="text-sm text-destructive">{t(`deposit.${loadError.key}`)}</p>
            {loadError.retryable && (
              <Button variant="outline" onClick={() => setAttempt((current) => current + 1)}>{t("deposit.retry")}</Button>
            )}
          </div>
        ) : (
          <div className="space-y-5">
            <div className="rounded-lg border border-border p-3 text-sm space-y-1">
              <p className="font-medium">{active ? t("deposit.activeVersion", { version: active.version }) : t("deposit.unconfigured")}</p>
              {active ? (
                <p className="break-words text-muted-foreground" dir="auto">
                  {active.name} · {t(`deposit.${active.deposit_type}`)}
                  {active.deposit_type !== "none" && <> · <bdi>{active.deposit_value} {active.deposit_type === "percentage" ? "%" : active.currency}</bdi></>}
                </p>
              ) : <p className="text-muted-foreground">{t("deposit.emptyHelp")}</p>}
            </div>
            {mismatch && (
              <p role="alert" className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                {t("deposit.currencyMismatch", { from: active.currency, to: currency })}
              </p>
            )}
            <form onSubmit={save} className="space-y-4">
              <fieldset disabled={saving} className="grid min-w-0 gap-4 sm:grid-cols-2">
                {input("name", t("deposit.name"))}
                {select("deposit_type", types)}
                {hasValue && input("deposit_value", t("deposit.value", { unit: draft.deposit_type === "percentage" ? "%" : currency }), true)}
                {draft.deposit_type === "percentage" && select("calculation_base", bases)}
                {hasValue && <>
                  {input("minimum_deposit", t("deposit.minimum", { currency }), true)}
                  {input("maximum_deposit", t("deposit.maximum", { currency }), true)}
                </>}
              </fieldset>
              {hasValue && <p id="deposit-number-help" className="text-xs text-muted-foreground">{t("deposit.numberHelp")}</p>}
              {dirty && validation && <p className="text-sm text-destructive">{t(`deposit.${validation}`, { limit: MAX_NAME_CHARS, currency })}</p>}
              {needsAck && (
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={acknowledged} disabled={saving}
                    onChange={(event) => { setAcknowledged(event.target.checked); setSaved(false); }} />
                  <span>{t("deposit.currencyAck", { currency })}</span>
                </label>
              )}
              {saveError && <p role="alert" className="text-sm text-destructive">{t(`deposit.${saveError}`, { currency })}</p>}
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p role="status" className="text-sm text-muted-foreground">{saved ? t("deposit.saved") : dirty ? t("deposit.dirty") : ""}</p>
                <Button type="submit" disabled={saving || Boolean(validation) || needsAck !== acknowledged || (!dirty && !mismatch)}>
                  {saving ? <Loader2 className="me-2 h-4 w-4 animate-spin" aria-hidden="true" /> : <Save className="me-2 h-4 w-4" aria-hidden="true" />}
                  {t(saving ? "deposit.saving" : "deposit.save")}
                </Button>
              </div>
            </form>
            {policies.length > 0 && (
              <div className="border-t border-border pt-4">
                <h3 className="mb-2 text-sm font-medium">{t("deposit.history")}</h3>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {policies.map((policy) => (
                    <li key={policy.id} className="break-words">
                      {t("deposit.version", { version: policy.version })} · <bdi>{policy.name}</bdi> · {t(`deposit.${policy.deposit_type}`)}
                      {policy.deposit_type !== "none" && <> · <bdi>{policy.deposit_value} {policy.deposit_type === "percentage" ? "%" : policy.currency}</bdi></>}
                      {policy.is_active && <> · {t("deposit.active")}</>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </SettingCard>
    </div>
  );
}
