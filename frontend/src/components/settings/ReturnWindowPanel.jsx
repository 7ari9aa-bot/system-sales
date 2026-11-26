/** What the shop promises when something comes back — read live, edited in one place only.
 *
 * A return is two objects: the WINDOW the system enforces (`pos.return_max_days`,
 * `pos.exchange_max_days`, read by the till and printed on the receipt) and the WORDING the
 * customer agent quotes (the `return` policy). Section 04 owns both, on
 * `/settings/store/business-policies`, because a promise split across two screens is a promise
 * nobody can keep. So this page does not offer a second editor: it shows the numbers that are
 * actually in force right now, says where they come from, and sends the owner there to change them.
 */
import React from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";

const WINDOW_KEYS = ["pos.return_max_days", "pos.exchange_max_days"];

export default function ReturnWindowPanel() {
  const t = useT();
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [rows, setRows] = React.useState([]);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      const res = await api(`/settings/effective?keys=${WINDOW_KEYS.join(",")}`);
      if (!alive) return;
      setRows(
        WINDOW_KEYS.map((key) => {
          const r = res?.[key];
          return {
            key,
            value: r?.value,
            source: r?.is_default
              ? t("settings.sales.returns.sourceDefault")
              : r?.is_inherited
                ? t("settings.sales.returns.sourceInherited")
                : t("settings.sales.returns.sourceSet"),
          };
        }),
      );
    })()
      .catch((e) => alive && setError(e?.message || t("settings.sales.returns.loadError")))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [t]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.sales.returns.loading")}
      </div>
    );
  }

  return (
    <SettingCard
      title={t("settings.sales.returns.title")}
      desc={t("settings.sales.returns.desc")}
    >
      {error ? (
        <p role="alert" className="text-[13px] text-destructive">
          {error}
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((r) => (
            <li key={r.key} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
              <span className="min-w-40">
                {r.key === "pos.return_max_days"
                  ? t("settings.sales.returns.returnWindow")
                  : t("settings.sales.returns.exchangeWindow")}
              </span>
              <span className="num font-medium">
                {r.value ?? "—"} {t("settings.sales.returns.days")}
              </span>
              <Badge tone="muted">{r.source}</Badge>
            </li>
          ))}
        </ul>
      )}

      <Link
        to="/settings/store/business-policies"
        className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-primary hover:underline"
      >
        <ArrowLeft className="h-3.5 w-3.5 rtl:rotate-180" />
        {t("settings.sales.returns.goEdit")}
      </Link>

      <p className="mt-2 text-[12px] text-muted-foreground">
        {t("settings.sales.returns.whyHere")}
      </p>
    </SettingCard>
  );
}
