/** Price lists: the named sets of prices, and what is inside each one.
 *
 * A price list is a document, not a switch, so this panel does not pretend to be a settings form.
 * It lists the real lists from `GET /pricing/price-lists`, creates one, archives one, and shows
 * the prices inside the selected list. Whether lists are USED at all is a registry key on this
 * same page, above this panel: turning it off keeps every row here and simply stops the resolver
 * from reading them.
 */
import React from "react";
import { Archive, Loader2, Plus } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/dashboard/ui";

const EMPTY = { name: "", code: "", priority: 0, is_default: false };

export default function PriceListsPanel() {
  const t = useT();
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [lists, setLists] = React.useState([]);
  const [selected, setSelected] = React.useState(null);
  const [items, setItems] = React.useState([]);
  const [form, setForm] = React.useState(EMPTY);
  const [saving, setSaving] = React.useState(false);

  const load = React.useCallback(async () => {
    const rows = await api("/pricing/price-lists");
    setLists(Array.isArray(rows) ? rows : []);
    return rows;
  }, []);

  React.useEffect(() => {
    let alive = true;
    load()
      .then((rows) => {
        if (!alive) return;
        if (rows?.length) setSelected(rows[0].id);
      })
      .catch((e) => alive && setError(e?.message || t("settings.sales.priceLists.loadError")))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [load, t]);

  React.useEffect(() => {
    if (!selected) {
      setItems([]);
      return;
    }
    let alive = true;
    api(`/pricing/price-lists/${selected}/items`)
      .then((rows) => alive && setItems(Array.isArray(rows) ? rows : []))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [selected]);

  const create = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api("/pricing/price-lists", { method: "POST", body: form });
      const rows = await load();
      setSelected(rows?.[0]?.id ?? null);
      setForm(EMPTY);
      setNotice(t("settings.sales.priceLists.created"));
    } catch (err) {
      setError(err?.message || t("settings.sales.priceLists.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const archive = async (id) => {
    setError("");
    setNotice("");
    try {
      await api(`/pricing/price-lists/${id}/archive`, { method: "POST" });
      await load();
      setNotice(t("settings.sales.priceLists.archived"));
    } catch (err) {
      setError(err?.message || t("settings.sales.priceLists.saveError"));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.sales.priceLists.loading")}
      </div>
    );
  }

  return (
    <SettingCard title={t("settings.sales.priceLists.title")} desc={t("settings.sales.priceLists.desc")}>
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

      {lists.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t("settings.sales.priceLists.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {lists.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
              <button
                type="button"
                onClick={() => setSelected(row.id)}
                className={`min-w-32 text-start hover:underline ${
                  selected === row.id ? "font-semibold text-primary" : ""
                }`}
              >
                {row.name}
              </button>
              <span className="num text-muted-foreground">{row.code}</span>
              <Badge tone="muted">{row.status}</Badge>
              {row.is_default ? (
                <Badge tone="muted">{t("settings.sales.priceLists.default")}</Badge>
              ) : null}
              {row.status === "active" ? (
                <button
                  type="button"
                  onClick={() => archive(row.id)}
                  className="ms-auto inline-flex items-center gap-1 text-[12px] text-muted-foreground hover:text-destructive"
                >
                  <Archive className="h-3.5 w-3.5" />
                  {t("settings.sales.priceLists.archive")}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {selected ? (
        <div className="mt-3 rounded-md border border-border p-2">
          <p className="mb-1 text-[12px] font-medium">
            {t("settings.sales.priceLists.itemsTitle")}
          </p>
          {items.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">
              {t("settings.sales.priceLists.itemsEmpty")}
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {items.map((item) => (
                <li key={item.id} className="flex flex-wrap gap-2 py-1 text-[12px]">
                  <span className="num text-muted-foreground">{item.variant_id.slice(0, 8)}</span>
                  <span className="num font-medium">{item.unit_price}</span>
                  <span className="num text-muted-foreground">
                    {t("settings.sales.priceLists.fromQuantity")} {item.min_quantity}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      <form onSubmit={create} className="mt-3 grid gap-2 sm:grid-cols-4">
        <input
          required
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder={t("settings.sales.priceLists.namePlaceholder")}
          className="rounded-md border border-input bg-background px-2 py-1 text-[13px]"
        />
        <input
          required
          value={form.code}
          onChange={(e) => setForm({ ...form, code: e.target.value })}
          placeholder={t("settings.sales.priceLists.codePlaceholder")}
          className="rounded-md border border-input bg-background px-2 py-1 text-[13px]"
        />
        <label className="flex items-center gap-1 text-[12px]">
          <input
            type="checkbox"
            checked={form.is_default}
            onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
          />
          {t("settings.sales.priceLists.makeDefault")}
        </label>
        <Button type="submit" size="sm" disabled={saving}>
          <Plus className="me-1 h-3.5 w-3.5" />
          {saving ? t("settings.sales.priceLists.saving") : t("settings.sales.priceLists.create")}
        </Button>
      </form>

      <p className="mt-3 text-[12px] text-muted-foreground">
        {t("settings.sales.priceLists.whereToEdit")}
      </p>
    </SettingCard>
  );
}
