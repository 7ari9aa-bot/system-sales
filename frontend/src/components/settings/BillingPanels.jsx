/** Section 19 — Plan & billing, over the billing module's own rows.
 *
 * The rule this section is built to: a page shows a number only if the server produced it,
 * and a page offers a control only if something reads it. That is why "payment methods" and
 * "renewal and upgrade" are notes rather than buttons — there is no stored payment
 * instrument and no checkout path until a payment provider is configured, and a dead button
 * is worse than an honest paragraph.
 *
 * What IS real:
 * - `GET /billing/subscription` now carries its plan (code, name, price, currency, interval)
 *   and the period bounds, because "which plan am I on" has to have one answer.
 * - `GET /billing/usage/summary` reports the same numbers the entitlement gate refuses on.
 * - `GET /billing/invoices` lists the tenant's invoices, frozen period snapshots included.
 * - `billing.auto_renew`, `billing.currency` and `billing.notify_before_renewal_days` are
 *   registry keys the trial-expiry service reads, and their home is `billing/current-plan`.
 */
import React from "react";
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useI18n, useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/regional";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";

function useJson(path) {
  const [state, setState] = React.useState({ loading: true, data: null, error: "" });
  React.useEffect(() => {
    let alive = true;
    api(path)
      .then((data) => alive && setState({ loading: false, data, error: "" }))
      .catch((e) => alive && setState({ loading: false, data: null, error: e?.message || "" }));
    return () => {
      alive = false;
    };
  }, [path]);
  return state;
}

function Frame({ title, desc, state, children, testId }) {
  const t = useT();
  return (
    <SettingCard title={title} desc={desc}>
      {state.loading ? (
        <div className="flex items-center gap-2 py-4 text-[13px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.data.loading")}
        </div>
      ) : state.error ? (
        <p role="alert" className="text-[13px] text-destructive">
          {t("settings.data.loadError")}
        </p>
      ) : (
        <div data-testid={testId}>{children}</div>
      )}
    </SettingCard>
  );
}

function Row({ label, value, last = false }) {
  return (
    <div
      className={
        last
          ? "flex items-center justify-between gap-4 py-2.5"
          : "flex items-center justify-between gap-4 border-b border-border py-2.5"
      }
    >
      <span className="text-[12.5px] text-muted-foreground">{label}</span>
      <span className="text-[13px] font-medium">{value}</span>
    </div>
  );
}

const STATUS_TONE = {
  active: "success",
  trialing: "warning",
  past_due: "error",
  canceled: "muted",
  expired: "muted",
};

export function SubscriptionPanel() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const state = useJson("/billing/subscription");
  const body = state.data || {};
  const plan = body.plan;

  return (
    <Frame
      title={t("settings.billing.plan.title")}
      desc={t("settings.billing.plan.desc")}
      state={state}
      testId="subscription-panel"
    >
      {body.status === "none" || !body.status ? (
        <p className="text-[13px] text-muted-foreground">{t("settings.billing.plan.none")}</p>
      ) : (
        <>
          <Row
            label={t("settings.billing.plan.name")}
            value={plan ? plan.name : t("settings.billing.plan.unknown")}
          />
          <Row
            label={t("settings.billing.plan.price")}
            value={
              plan
                ? `${plan.price} ${plan.currency} / ${plan.interval === "year" ? (isAr ? "سنة" : "year") : isAr ? "شهر" : "month"}`
                : "—"
            }
          />
          <Row
            label={t("settings.billing.plan.status")}
            value={
              <Badge tone={STATUS_TONE[body.status] || "muted"}>
                {t(`settings.billing.plan.statuses.${body.status}`, body.status)}
              </Badge>
            }
          />
          <Row
            label={
              body.status === "trialing"
                ? t("settings.billing.plan.trialEnds")
                : t("settings.billing.plan.renews")
            }
            value={body.current_period_end ? formatDate(body.current_period_end) : "—"}
          />
          <Row
            label={t("settings.billing.plan.cancelAtEnd")}
            value={
              body.cancel_at_period_end ? (isAr ? "متوقف في نهاية الفترة" : "Ends at period end") : "—"
            }
            last
          />
        </>
      )}
      <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
        {t("settings.billing.plan.whereToEdit")}{" "}
        {/* The note says the plan limits are counted elsewhere, so it carries the way there:
            billing stays money only, and the numbers have one home. */}
        <Link to="/settings/billing/usage" className="font-medium text-primary hover:underline">
          {t("settings.billing.plan.usageLink")}
        </Link>
      </p>
    </Frame>
  );
}

/** Metered features against their limits, from the numbers the gate itself uses. */
export function PlanUsagePanel() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const state = useJson("/billing/usage/summary");
  const rows = Array.isArray(state.data?.items) ? state.data.items : [];

  return (
    <Frame
      title={t("settings.billing.usage.title")}
      desc={t("settings.billing.usage.desc")}
      state={state}
      testId="plan-usage"
    >
      {rows.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t("settings.billing.usage.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row) => {
            const unlimited = Boolean(row.is_unlimited) || row.limit == null;
            const used = Number(row.used) || 0;
            const limit = Number(row.limit) || 0;
            const pct = unlimited || limit <= 0 ? 0 : Math.min(100, (used / limit) * 100);
            return (
              <li key={row.feature} className="py-2.5">
                <div className="flex items-center justify-between gap-3 text-[12.5px]">
                  <span>{row.feature}</span>
                  <span className="tabular-nums text-muted-foreground">
                    {used.toLocaleString()}
                    {unlimited
                      ? ` / ${isAr ? "بلا حد" : "unlimited"}`
                      : ` / ${limit.toLocaleString()}`}
                  </span>
                </div>
                {!unlimited && (
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface">
                    <div
                      className={pct >= 100 ? "h-full rounded-full bg-destructive" : "h-full rounded-full bg-primary"}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
        {t("settings.billing.usage.whereToEdit")}{" "}
        <Link className="underline" to="/usage">
          {t("settings.billing.usage.aiConsumption")}
        </Link>
      </p>
    </Frame>
  );
}

/** One invoice row, humanised. Kept pure so the money formatting is testable. */
export function invoiceRow(row) {
  if (!row || typeof row !== "object") return [];
  const pairs = [
    ["number", row.number],
    ["status", row.status],
    ["total", row.total == null ? null : `${row.total} ${row.currency || ""}`.trim()],
    ["issued", row.issued_at ? formatDate(row.issued_at) : null],
    ["period", row.period_start && row.period_end ? `${row.period_start} → ${row.period_end}` : null],
  ];
  return pairs.filter(([, value]) => value !== null && value !== undefined && value !== "");
}

export function InvoicesPanel() {
  const t = useT();
  const state = useJson("/billing/invoices");
  const rows = Array.isArray(state.data?.items) ? state.data.items : [];

  return (
    <Frame
      title={t("settings.billing.invoices.title")}
      desc={t("settings.billing.invoices.desc")}
      state={state}
      testId="invoices-panel"
    >
      {rows.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t("settings.billing.invoices.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row) => (
            <li key={row.id} className="flex flex-wrap gap-x-4 gap-y-1 py-2 text-[12px]">
              {invoiceRow(row).map(([label, value]) => (
                <span key={label} className="text-muted-foreground">
                  {t(`settings.billing.invoices.fields.${label}`, label)}:{" "}
                  <span className="text-foreground">{value}</span>
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
        {t("settings.billing.invoices.whereToEdit")}
      </p>
    </Frame>
  );
}
