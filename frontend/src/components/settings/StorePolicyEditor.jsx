/** The promises a shop publishes, edited one row at a time.
 *
 * A store policy is an ordinary knowledge item the customer agent answers from (see
 * backend `ai/policies.py`), so the same row is written here and read there: no copy to drift.
 * `keys` decides which of them a page shows, because the map gives each policy exactly one home
 * — opening times on the working hours page, the return and exchange promise on business
 * policies — and no page may offer a second editor for a policy another page already owns.
 */
import React from "react";
import { Check, Loader2, Save } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export default function StorePolicyEditor({ keys }) {
  const t = useT();
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [maxChars, setMaxChars] = React.useState(1500);
  // key -> { title, saved, draft, published, saving, notice, error }
  const [rows, setRows] = React.useState([]);

  React.useEffect(() => {
    let alive = true;
    api("/ai/store-policies")
      .then((res) => {
        if (!alive) return;
        setMaxChars(res.max_chars || 1500);
        const items = Array.isArray(res?.items) ? res.items : [];
        const wanted = keys && keys.length ? items.filter((p) => keys.includes(p.key)) : items;
        setRows(
          wanted.map((p) => ({
            key: p.key,
            title: p.title,
            saved: p.content,
            draft: p.content,
            published: p.published,
            saving: false,
            notice: "",
            error: "",
          })),
        );
      })
      .catch((e) => alive && setError(e?.message || t("policies.loadError")))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // `keys` is a literal list at every call site; joining it keeps the effect stable.
  }, [t, (keys || []).join(",")]);

  const patch = (key, changes) =>
    setRows((current) => current.map((r) => (r.key === key ? { ...r, ...changes } : r)));

  async function save(row) {
    patch(row.key, { saving: true, notice: "", error: "" });
    try {
      const out = await api(`/ai/store-policies/${row.key}`, {
        method: "PUT",
        body: { content: row.draft },
      });
      patch(row.key, {
        saving: false,
        saved: out.content,
        draft: out.content,
        published: out.published,
        notice: out.published ? t("policies.saved") : t("policies.removed"),
      });
    } catch (e) {
      patch(row.key, { saving: false, error: e?.message || t("policies.saveError") });
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> {t("policies.loading")}
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="text-[13px] text-destructive">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {rows.map((row) => {
        const trimmed = row.draft.trim();
        const over = trimmed.length > maxChars;
        const dirty = row.draft.trim() !== row.saved.trim();
        return (
          <SettingCard
            key={row.key}
            title={t(`policies.title.${row.key}`, row.title)}
            desc={row.published ? t("policies.published") : t("policies.unpublished")}
          >
            <Textarea
              dir="auto"
              rows={5}
              value={row.draft}
              aria-label={t(`policies.title.${row.key}`, row.title)}
              placeholder={t(`policies.placeholder.${row.key}`)}
              onChange={(e) => patch(row.key, { draft: e.target.value, notice: "", error: "" })}
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <span
                className={`num text-[12px] ${over ? "text-destructive" : "text-muted-foreground"}`}
              >
                {trimmed.length} / {maxChars}
              </span>
              <div className="flex items-center gap-3">
                {row.notice && (
                  <span className="flex items-center gap-1 text-[12.5px] text-emerald-600">
                    <Check className="h-3.5 w-3.5" /> {row.notice}
                  </span>
                )}
                {row.error && (
                  <span role="alert" className="text-[12.5px] text-destructive">
                    {row.error}
                  </span>
                )}
                <Button
                  type="button"
                  size="sm"
                  disabled={row.saving || over || !dirty}
                  onClick={() => save(row)}
                >
                  {row.saving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4" />
                  )}
                  <span className="ms-1.5">
                    {!trimmed && row.published ? t("policies.remove") : t("policies.save")}
                  </span>
                </Button>
              </div>
            </div>
          </SettingCard>
        );
      })}
    </div>
  );
}
