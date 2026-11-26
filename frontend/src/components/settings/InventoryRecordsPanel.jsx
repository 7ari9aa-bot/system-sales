/** A read-only list of inventory records that the inventory module already owns.
 *
 * Warehouses, transfers and stocktakes are places and documents, not settings: you do not
 * configure them on a settings page. But the settings that govern them are meaningless without
 * seeing what they apply to, so each page shows the real rows the module reports, says where the
 * records are actually created and changed, and leaves the switches to the registry.
 */
import React from "react";
import { Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";

export default function InventoryRecordsPanel({
  endpoint,
  titleKey,
  descKey,
  emptyKey,
  loadingKey,
  loadErrorKey,
  footerKey,
  columns = [],
}) {
  const t = useT();
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [rows, setRows] = React.useState([]);

  React.useEffect(() => {
    let alive = true;
    api(endpoint)
      .then((res) => alive && setRows(Array.isArray(res) ? res : []))
      .catch((e) => alive && setError(e?.message || t(loadErrorKey)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [endpoint, loadErrorKey, t]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> {t(loadingKey)}
      </div>
    );
  }

  return (
    <SettingCard title={t(titleKey)} desc={t(descKey)}>
      {error ? (
        <p role="alert" className="text-[13px] text-destructive">
          {error}
        </p>
      ) : rows.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t(emptyKey)}</p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row, i) => (
            <li key={row.id || i} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
              {columns.map((c) =>
                c.kind === "badge" ? (
                  <Badge key={c.key} tone="muted">
                    {row[c.key] ?? "—"}
                  </Badge>
                ) : (
                  <span
                    key={c.key}
                    className={
                      c.kind === "num" ? "num text-muted-foreground" : "text-muted-foreground"
                    }
                  >
                    {row[c.key] ?? "—"}
                  </span>
                ),
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-3 text-[12px] text-muted-foreground">{t(footerKey)}</p>
    </SettingCard>
  );
}
