/** The categories the catalogue actually files products under.
 *
 * Categories are shop data, not a setting, so this panel does not try to be the catalogue screen:
 * it shows the real list and lets the owner add a category, and says where the rest of the work
 * happens. The point of the page in the Settings Center is to answer "what do I have", which a
 * switch could not do.
 */
import React from "react";
import { Check, Loader2, Plus } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function CategoriesPanel() {
  const t = useT();
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [name, setName] = React.useState("");
  const [rows, setRows] = React.useState([]);

  const load = React.useCallback(async () => {
    const res = await api("/catalog/categories");
    setRows(Array.isArray(res) ? res : []);
  }, []);

  React.useEffect(() => {
    let alive = true;
    load()
      .catch((e) => alive && setError(e?.message || t("settings.catalog.categories.loadError")))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [load, t]);

  async function add(e) {
    e?.preventDefault?.();
    const trimmed = name.trim();
    if (!trimmed) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api("/catalog/categories", { method: "POST", body: { name: trimmed } });
      setName("");
      await load();
      setNotice(t("settings.catalog.categories.added"));
    } catch (err) {
      setError(err?.message || t("settings.catalog.categories.saveError"));
    } finally {
      setSaving(false);
    }
  }

  const byId = new Map(rows.map((r) => [r.id, r]));

  return (
    <SettingCard
      title={t("settings.catalog.categories.title")}
      desc={t("settings.catalog.categories.desc")}
    >
      {loading ? (
        <div className="flex items-center gap-2 py-4 text-[13px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.catalog.categories.loading")}
        </div>
      ) : (
        <>
          {rows.length === 0 ? (
            <p className="py-2 text-[13px] text-muted-foreground">
              {t("settings.catalog.categories.empty")}
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {rows.map((r) => (
                <li key={r.id} className="flex items-center gap-2 py-1.5 text-[13px]">
                  <span>{r.name}</span>
                  {r.parent_id && byId.get(r.parent_id) && (
                    <span className="text-[12px] text-muted-foreground">
                      {t("settings.catalog.categories.under")} {byId.get(r.parent_id).name}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}

          <form className="mt-3 flex flex-wrap items-center gap-2" onSubmit={add}>
            <Input
              className="min-w-48 flex-1"
              value={name}
              aria-label={t("settings.catalog.categories.newName")}
              placeholder={t("settings.catalog.categories.newName")}
              onChange={(e) => setName(e.target.value)}
            />
            <Button type="submit" size="sm" disabled={saving || !name.trim()}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              <span className="ms-1.5">{t("settings.catalog.categories.add")}</span>
            </Button>
          </form>

          {notice && (
            <p className="mt-2 flex items-center gap-1 text-[12.5px] text-emerald-600">
              <Check className="h-3.5 w-3.5" /> {notice}
            </p>
          )}
          {error && (
            <p role="alert" className="mt-2 text-[12.5px] text-destructive">
              {error}
            </p>
          )}
          <p className="mt-3 text-[12px] text-muted-foreground">
            {t("settings.catalog.categories.whereNote")}
          </p>
        </>
      )}
    </SettingCard>
  );
}
