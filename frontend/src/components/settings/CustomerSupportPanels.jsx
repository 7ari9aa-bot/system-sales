/** The two section 11 pages that need more than a list: support hours, and escalation.
 *
 * Support hours already have exactly one editor — the store's working hours on
 * /settings/store/working-hours, which publishes the prose the customer agent answers "when are
 * you open" from. A second editor here would be the duplicate the whole Settings Center exists to
 * prevent, so this page reads that promise back and links to its home.
 *
 * Escalation is real and already modelled: `sla_policies` carries the first-response and
 * resolution minutes, optionally per channel, and the SLA clock reads them
 * (modules/operations/sla.py). The panel edits those rows through the module's own endpoints
 * instead of inventing a parallel pair of keys. The Customer Agent's own handover behaviour is
 * section 13 and is linked, never duplicated here.
 */
import React from "react";
import { ArrowRight, Loader2, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/dashboard/ui";

export function SupportHoursLink() {
  const t = useT();
  // The promise the customer agent quotes, read from the same store policies the editor writes.
  const [hours, setHours] = React.useState(null);
  React.useEffect(() => {
    let alive = true;
    api("/ai/store-policies")
      .then((res) => {
        const rows = Array.isArray(res) ? res : (res?.items ?? []);
        const row = rows.find((r) => r.key === "hours");
        if (alive) setHours(row?.value ?? row?.text ?? null);
      })
      .catch(() => alive && setHours(null));
    return () => {
      alive = false;
    };
  }, []);
  return (
    <SettingCard
      title={t("settings.customers.supportHours.title")}
      desc={t("settings.customers.supportHours.desc")}
    >
      {hours ? (
        <p className="mb-2 whitespace-pre-line rounded-md border border-border p-2 text-[13px]">
          {hours}
        </p>
      ) : (
        <p className="mb-2 text-[13px] text-muted-foreground">
          {t("settings.customers.supportHours.empty")}
        </p>
      )}
      <Link
        to="/settings/store/working-hours"
        className="inline-flex items-center gap-1 text-[13px] font-medium text-primary hover:underline"
      >
        {t("settings.customers.supportHours.goEdit")}
        <ArrowRight className="h-3.5 w-3.5 rtl:rotate-180" />
      </Link>
      <p className="mt-3 text-[12px] text-muted-foreground">
        {t("settings.customers.supportHours.why")}
      </p>
    </SettingCard>
  );
}

const EMPTY = {
  name: "",
  first_response_minutes: 60,
  resolution_minutes: 1440,
  applies_to_channel: "",
  is_default: false,
};

export function EscalationPanel({ policies = [], onSaved }) {
  const t = useT();
  const [form, setForm] = React.useState(EMPTY);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api("/sla/policies", {
        method: "PUT",
        body: {
          name: form.name,
          first_response_minutes: Number(form.first_response_minutes),
          resolution_minutes: Number(form.resolution_minutes),
          applies_to_channel: form.applies_to_channel || null,
          is_default: form.is_default,
        },
      });
      setForm(EMPTY);
      setNotice(t("settings.customers.escalation.saved"));
      onSaved?.();
    } catch (err) {
      setError(err?.message || t("settings.customers.escalation.saveError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingCard
      title={t("settings.customers.escalation.title")}
      desc={t("settings.customers.escalation.desc")}
    >
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

      {policies.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          {t("settings.customers.escalation.empty")}
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {policies.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
              <span className="min-w-28 font-medium">{p.name}</span>
              <span className="num text-muted-foreground">
                {t("settings.customers.escalation.firstResponse")} {p.first_response_minutes}
              </span>
              <span className="num text-muted-foreground">
                {t("settings.customers.escalation.resolution")} {p.resolution_minutes}
              </span>
              {p.applies_to_channel ? <Badge tone="muted">{p.applies_to_channel}</Badge> : null}
              {p.is_default ? (
                <Badge tone="muted">{t("settings.customers.escalation.isDefault")}</Badge>
              ) : null}
              <Badge tone="muted">{p.status}</Badge>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={save} className="mt-3 grid gap-2 sm:grid-cols-5">
        <input
          required
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder={t("settings.customers.escalation.namePlaceholder")}
          className="rounded-md border border-input bg-background px-2 py-1 text-[13px]"
        />
        <input
          required
          type="number"
          min="1"
          value={form.first_response_minutes}
          onChange={(e) => setForm({ ...form, first_response_minutes: e.target.value })}
          placeholder={t("settings.customers.escalation.firstResponse")}
          className="num rounded-md border border-input bg-background px-2 py-1 text-[13px]"
        />
        <input
          required
          type="number"
          min="1"
          value={form.resolution_minutes}
          onChange={(e) => setForm({ ...form, resolution_minutes: e.target.value })}
          placeholder={t("settings.customers.escalation.resolution")}
          className="num rounded-md border border-input bg-background px-2 py-1 text-[13px]"
        />
        <input
          value={form.applies_to_channel}
          onChange={(e) => setForm({ ...form, applies_to_channel: e.target.value })}
          placeholder={t("settings.customers.escalation.channelPlaceholder")}
          className="rounded-md border border-input bg-background px-2 py-1 text-[13px]"
        />
        <Button type="submit" size="sm" disabled={saving}>
          <Plus className="h-4 w-4" />
          <span className="ms-1.5">
            {saving
              ? t("settings.customers.escalation.saving")
              : t("settings.customers.escalation.save")}
          </span>
        </Button>
      </form>

      <div className="mt-3 space-y-1 text-[12px] text-muted-foreground">
        <p>{t("settings.customers.escalation.clockNote")}</p>
        <Link
          to="/settings/ai/customer-agent"
          className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
        >
          {t("settings.customers.escalation.agentLink")}
          <ArrowRight className="h-3.5 w-3.5 rtl:rotate-180" />
        </Link>
      </div>
    </SettingCard>
  );
}

/** Reads the SLA policies and hands them to the escalation panel. */
export function EscalationSection() {
  const t = useT();
  const [policies, setPolicies] = React.useState(null);

  const load = React.useCallback(() => {
    api("/sla/policies")
      .then((res) => setPolicies(Array.isArray(res?.items) ? res.items : (res?.items ?? [])))
      .catch(() => setPolicies([]));
  }, []);

  React.useEffect(load, [load]);

  if (policies === null) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.customers.escalation.loading")}
      </div>
    );
  }
  return <EscalationPanel policies={policies} onSaved={load} />;
}
