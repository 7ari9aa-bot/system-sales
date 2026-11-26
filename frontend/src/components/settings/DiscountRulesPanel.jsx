/** Offers: the rules that take money off an order, and what each one is allowed to do.
 *
 * The panel shows the real rules from `GET /pricing/discount-rules` and creates one. It never
 * shows a stored total: a rule has no total, because the same rule on a different basket gives a
 * different number. The policy that decides whether offers auto-apply, whether they stack, and
 * the ceiling on the whole order sits in the registry keys above this panel.
 */
import React from "react";
import { Loader2, Plus } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/dashboard/ui";

const EMPTY = { name: "", kind: "percent", value: "", scope: "order", code: "" };

export default function DiscountRulesPanel() {
  const t = useT();
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [rules, setRules] = React.useState([]);
  const [form, setForm] = React.useState(EMPTY);
  const [saving, setSaving] = React.useState(false);

  const load = React.useCallback(async () => {
    const rows = await api("/pricing/discount-rules");
    setRules(Array.isArray(rows) ? rows : []);
  }, []);

  React.useEffect(() => {
    let alive = true;
    load()
      .catch((e) => alive && setError(e?.message || t("settings.sales.offers.loadError")))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [load, t]);

  const create = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api("/pricing/discount-rules", {
        method: "POST",
        body: {
          name: form.name,
          kind: form.kind,
          value: Number(form.value),
          scope: form.scope,
          code: form.code.trim() || null,
          requires_code: Boolean(form.code.trim()),
        },
      });
      await load();
      setForm(EMPTY);
      setNotice(t("settings.sales.offers.created"));
    } catch (err) {
      setError(err?.message || t("settings.sales.offers.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (rule) => {
    setError("");
    setNotice("");
    try {
      await api(`/pricing/discount-rules/${rule.id}/status`, {
        method: "POST",
        body: { status: rule.status === "active" ? "archived" : "active" },
      });
      await load();
      setNotice(t("settings.sales.offers.updated"));
    } catch (err) {
      setError(err?.message || t("settings.sales.offers.saveError"));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.sales.offers.loading")}
      </div>
    );
  }

  return (
    <SettingCard title={t("settings.sales.offers.title")} desc={t("settings.sales.offers.desc")}>
      {error ? (
        <p role="alert" className="mb-2 text-[13px] text-destructive">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="mb-2 text-[13px] text-emerald-600">
          {notice}
        </p>
      ) : null}

      {rules.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t("settings.sales.offers.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {rules.map((rule) => (
            <li key={rule.id} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
              <span className="min-w-32">{rule.name}</span>
              <span className="num font-medium">
                {rule.kind === "percent" ? `${rule.value}%` : rule.value}
              </span>
              <span className="text-muted-foreground">
                {t(`settings.sales.offers.scope.${rule.scope}`)}
              </span>
              {rule.code ? <Badge tone="muted">{rule.code}</Badge> : null}
              <Badge tone="muted">{rule.status}</Badge>
              <button
                type="button"
                onClick={() => toggle(rule)}
                className="ms-auto text-[12px] text-muted-foreground hover:text-primary"
              >
                {rule.status === "active"
                  ? t("settings.sales.offers.pause")
                  : t("settings.sales.offers.resume")}
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={create} className="mt-3 grid gap-2 sm:grid-cols-5">
        <input
          required
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder={t("settings.sales.offers.namePlaceholder")}
          className="rounded-md border border-input bg-background px-2 py-1 text-[13px]"
        />
        <select
          value={form.kind}
          onChange={(e) => setForm({ ...form, kind: e.target.value })}
          className="rounded-md border border-input bg-background px-2 py-1 text-[13px]"
        >
          <option value="percent">{t("settings.sales.offers.kind.percent")}</option>
          <option value="amount">{t("settings.sales.offers.kind.amount")}</option>
        </select>
        <input
          required
          type="number"
          min="0"
          step="0.01"
          value={form.value}
          onChange={(e) => setForm({ ...form, value: e.target.value })}
          placeholder={t("settings.sales.offers.valuePlaceholder")}
          className="num rounded-md border border-input bg-background px-2 py-1 text-[13px]"
        />
        <input
          value={form.code}
          onChange={(e) => setForm({ ...form, code: e.target.value })}
          placeholder={t("settings.sales.offers.codePlaceholder")}
          className="rounded-md border border-input bg-background px-2 py-1 text-[13px]"
        />
        <Button type="submit" size="sm" disabled={saving}>
          <Plus className="h-4 w-4" />
          <span className="ms-1.5">
            {saving ? t("settings.sales.offers.saving") : t("settings.sales.offers.create")}
          </span>
        </Button>
      </form>

      <p className="mt-3 text-[12px] text-muted-foreground">
        {t("settings.sales.offers.whereToEdit")}
      </p>
    </SettingCard>
  );
}
