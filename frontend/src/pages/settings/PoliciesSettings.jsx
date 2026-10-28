import React from "react";
import { Check, Loader2, Save } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

/**
 * سياسات المتجر الأساسية — اللي الوكيل بيجاوب منها العميل (استبدال، استرجاع، شحن، مواعيد).
 *
 * التاجر بيكتب النص بس، والعناوين ثابتة من السيرفر. الوكيل بيقرأ اللي اتحفظ هنا زي ما هو،
 * فمفيش نص افتراضي: سياسة مش مكتوبة معناها إن الوكيل هيقول للعميل إنها مش متاحة عنده.
 * نص فاضي + حفظ = مسح السياسة.
 */
export default function PoliciesSettings() {
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
        setRows(
          res.items.map((p) => ({
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
  }, [t]);

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

  return (
    <SettingsShell title={t("settings.nav.policies")} subtitle={t("settings.policies.desc")}>
      {loading ? (
        <div className="flex items-center gap-2 text-[13px] text-muted-foreground py-8">
          <Loader2 className="h-4 w-4 animate-spin" /> {t("policies.loading")}
        </div>
      ) : error ? (
        <div role="alert" className="rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-[13px]">
          {error}
        </div>
      ) : (
        <div className="space-y-5">
          {rows.map((row) => {
            const trimmed = row.draft.trim();
            const over = trimmed.length > maxChars;
            const dirty = row.draft.trim() !== row.saved.trim();
            return (
              <SettingCard
                key={row.key}
                title={row.title}
                desc={row.published ? t("policies.published") : t("policies.unpublished")}
              >
                <Textarea
                  dir="auto"
                  rows={5}
                  value={row.draft}
                  aria-label={row.title}
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
                    <Button type="button" size="sm" disabled={row.saving || over || !dirty} onClick={() => save(row)}>
                      {row.saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                      <span className="ms-1.5">{!trimmed && row.published ? t("policies.remove") : t("policies.save")}</span>
                    </Button>
                  </div>
                </div>
              </SettingCard>
            );
          })}
        </div>
      )}
    </SettingsShell>
  );
}
