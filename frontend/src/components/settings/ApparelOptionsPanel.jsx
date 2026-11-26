/** The shop's own size sets and colours — the apparel case the map asks this section to survive.
 *
 * A shop that sells clothing does not want a hundred free-text attributes: it wants "Shirts:
 * S–XXL" and "Colours: white, navy, olive" defined once, and thousands of products pointing at
 * them. That is exactly what `GET/PUT /catalog/apparel/options` already stores, so this page
 * edits it rather than inventing a parallel attribute model.
 *
 * Saving replaces the whole list; resetting goes back to the built-in defaults the shop started
 * with (`DELETE /catalog/apparel/options`), which is why the button says so before it acts.
 */
import React from "react";
import { Check, Loader2, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/dashboard/ui";

const EMPTY_SET = { name: "", sizes: "" };

export default function ApparelOptionsPanel() {
  const t = useT();
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [customised, setCustomised] = React.useState(false);
  // [{ name, sizes }] — sizes kept as the comma string the owner typed.
  const [sets, setSets] = React.useState([]);
  // [{ name, hex }]
  const [colours, setColours] = React.useState([]);

  const load = React.useCallback(async () => {
    const res = await api("/catalog/apparel/options");
    setCustomised(Boolean(res?.customised));
    const sizeSets = res?.size_sets || {};
    setSets(
      Object.entries(sizeSets).map(([name, sizes]) => ({
        name,
        sizes: Array.isArray(sizes) ? sizes.join(", ") : String(sizes ?? ""),
      })),
    );
    setColours(
      (Array.isArray(res?.colours) ? res.colours : []).map((c) => ({
        name: c?.name ?? "",
        hex: c?.hex ?? "",
      })),
    );
  }, []);

  React.useEffect(() => {
    let alive = true;
    load()
      .catch((e) => alive && setError(e?.message || t("settings.catalog.options.loadError")))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [load, t]);

  const patchSet = (i, changes) =>
    setSets((cur) => cur.map((s, idx) => (idx === i ? { ...s, ...changes } : s)));
  const patchColour = (i, changes) =>
    setColours((cur) => cur.map((c, idx) => (idx === i ? { ...c, ...changes } : c)));

  async function run(fn, okMessage) {
    setSaving(true);
    setNotice("");
    setError("");
    try {
      await fn();
      await load();
      setNotice(okMessage);
    } catch (e) {
      setError(e?.message || t("settings.catalog.options.saveError"));
    } finally {
      setSaving(false);
    }
  }

  const saveSizeSets = () => {
    const payload = {};
    for (const s of sets) {
      const name = s.name.trim();
      if (!name) continue;
      payload[name] = s.sizes
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);
    }
    return run(
      () =>
        api("/catalog/apparel/options/size-sets", {
          method: "PUT",
          body: { size_sets: payload },
        }),
      t("settings.catalog.options.saved"),
    );
  };

  const saveColours = () =>
    run(
      () =>
        api("/catalog/apparel/options/colours", {
          method: "PUT",
          body: {
            colours: colours
              .filter((c) => c.name.trim())
              .map((c) => ({ name: c.name.trim(), hex: c.hex.trim() || null })),
          },
        }),
      t("settings.catalog.options.saved"),
    );

  const resetAll = () =>
    run(() => api("/catalog/apparel/options", { method: "DELETE" }), t("settings.catalog.options.reset"));

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.catalog.options.loading")}
      </div>
    );
  }

  return (
    <>
      <SettingCard
        title={t("settings.catalog.options.sizes.title")}
        desc={t("settings.catalog.options.sizes.desc")}
      >
        {sets.length === 0 && (
          <p className="py-2 text-[13px] text-muted-foreground">
            {t("settings.catalog.options.sizes.empty")}
          </p>
        )}
        <div className="space-y-2">
          {sets.map((s, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <Input
                className="w-40"
                value={s.name}
                aria-label={t("settings.catalog.options.setName")}
                placeholder={t("settings.catalog.options.setName")}
                onChange={(e) => patchSet(i, { name: e.target.value })}
              />
              <Input
                className="min-w-48 flex-1"
                dir="ltr"
                value={s.sizes}
                aria-label={t("settings.catalog.options.setSizes")}
                placeholder="S, M, L, XL"
                onChange={(e) => patchSet(i, { sizes: e.target.value })}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={t("settings.catalog.options.removeSet")}
                onClick={() => setSets((cur) => cur.filter((_, idx) => idx !== i))}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setSets((cur) => [...cur, { ...EMPTY_SET }])}
          >
            <Plus className="h-4 w-4" />
            <span className="ms-1.5">{t("settings.catalog.options.addSet")}</span>
          </Button>
          <Button type="button" size="sm" disabled={saving} onClick={saveSizeSets}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            <span className="ms-1.5">{t("policies.save")}</span>
          </Button>
        </div>
      </SettingCard>

      <SettingCard
        title={t("settings.catalog.options.colours.title")}
        desc={t("settings.catalog.options.colours.desc")}
      >
        {colours.length === 0 && (
          <p className="py-2 text-[13px] text-muted-foreground">
            {t("settings.catalog.options.colours.empty")}
          </p>
        )}
        <div className="space-y-2">
          {colours.map((c, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <Input
                className="w-40"
                value={c.name}
                aria-label={t("settings.catalog.options.colourName")}
                placeholder={t("settings.catalog.options.colourName")}
                onChange={(e) => patchColour(i, { name: e.target.value })}
              />
              <Input
                className="w-28"
                dir="ltr"
                value={c.hex}
                aria-label={t("settings.catalog.options.colourHex")}
                placeholder="#ffffff"
                onChange={(e) => patchColour(i, { hex: e.target.value })}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={t("settings.catalog.options.removeColour")}
                onClick={() => setColours((cur) => cur.filter((_, idx) => idx !== i))}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setColours((cur) => [...cur, { name: "", hex: "" }])}
          >
            <Plus className="h-4 w-4" />
            <span className="ms-1.5">{t("settings.catalog.options.addColour")}</span>
          </Button>
          <Button type="button" size="sm" disabled={saving} onClick={saveColours}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            <span className="ms-1.5">{t("policies.save")}</span>
          </Button>
          {customised && (
            <Button type="button" variant="ghost" size="sm" disabled={saving} onClick={resetAll}>
              <RotateCcw className="h-4 w-4" />
              <span className="ms-1.5">{t("settings.catalog.options.resetAction")}</span>
            </Button>
          )}
          {!customised && <Badge tone="muted">{t("settings.catalog.options.builtIn")}</Badge>}
        </div>
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
      </SettingCard>
    </>
  );
}
