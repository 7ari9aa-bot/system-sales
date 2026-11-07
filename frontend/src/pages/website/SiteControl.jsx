import React from "react";
import { ExternalLink, Globe, History, Paintbrush, RefreshCw, Rocket, Save } from "lucide-react";
import { Badge, SectionCard } from "@/components/dashboard/ui";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/** The website control page: status, identity (name + theme — live, not
 *  versioned), section content (versioned: edits clone the live version into
 *  a draft), publish, and the version history with rollback. */

const SECTION_TYPE_LABELS = {
  hero: ["البانر الرئيسي", "Hero"],
  rich_text: ["نص حر", "Rich text"],
  image_text: ["صورة ونص", "Image + text"],
  product_grid: ["شبكة المنتجات", "Product grid"],
  collection_grid: ["شبكة المجموعات", "Collection grid"],
  testimonial: ["رأي عميل", "Testimonial"],
  faq: ["أسئلة شائعة", "FAQ"],
  cta: ["دعوة لاتخاذ إجراء", "CTA"],
  newsletter: ["النشرة البريدية", "Newsletter"],
  footer: ["تذييل الصفحة", "Footer"],
};

const COLOR_TOKENS = new Set(["primary", "background", "secondary", "accent"]);

function isColorValue(value) {
  return /^#[0-9a-fA-F]{3,8}$/.test(String(value ?? ""));
}

export default function SiteControl({ overview, onMutate }) {
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const L = (ar, en) => (isAr ? ar : en);
  const website = overview?.website;

  const [content, setContent] = React.useState(null);
  const [schema, setSchema] = React.useState(null);
  const [versions, setVersions] = React.useState([]);
  const [busy, setBusy] = React.useState("");
  const [message, setMessage] = React.useState(null);
  const [attempt, setAttempt] = React.useState(0);

  const [name, setName] = React.useState(website?.name ?? "");
  const [tokens, setTokens] = React.useState(website?.theme_tokens ?? {});
  // Local edit buffers per section id (empty = untouched).
  const [sectionEdits, setSectionEdits] = React.useState({});

  React.useEffect(() => {
    let alive = true;
    setBusy("load");
    Promise.all([api("/website/content"), api("/website/editor-schema"), api("/website/versions")])
      .then(([c, s, v]) => {
        if (!alive) return;
        setContent(c);
        setSchema(s?.sections ?? []);
        setVersions(v?.versions ?? []);
      })
      .catch((err) => {
        if (alive) setMessage({ kind: "err", text: err?.message || L("تعذر تحميل المحتوى", "Could not load content") });
      })
      .finally(() => alive && setBusy(""));
    return () => {
      alive = false;
    };
     
  }, [attempt]);

  const refreshAll = () => {
    setAttempt((n) => n + 1);
    onMutate();
  };

  const schemaFor = (type) => schema?.find((s) => s.type === type)?.fields ?? [];

  const saveIdentity = async () => {
    setBusy("identity");
    setMessage(null);
    try {
      await api("/website/content/identity", {
        method: "POST",
        body: JSON.stringify({ name, theme_tokens: tokens }),
      });
      setMessage({ kind: "ok", text: L("تم حفظ الهوية وظهرت على الموقع", "Identity saved — live on the site") });
      refreshAll();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر الحفظ", "Could not save") });
    } finally {
      setBusy("");
    }
  };

  const saveSection = async (sectionId, type, currentProps) => {
    const edit = sectionEdits[sectionId];
    if (edit === undefined) return;
    const props = { ...currentProps, ...edit };
    setBusy(`section-${sectionId}`);
    setMessage(null);
    try {
      await api("/website/content/section", {
        method: "POST",
        body: JSON.stringify({ section_id: sectionId, props }),
      });
      setMessage({
        kind: "ok",
        text: L("اتعدلت في مسودة — انشر عشان تظهر", "Saved to the draft — publish to go live"),
      });
      setSectionEdits((prev) => ({ ...prev, [sectionId]: undefined }));
      refreshAll();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر حفظ القسم", "Could not save the section") });
    } finally {
      setBusy("");
    }
  };

  const publish = async () => {
    setBusy("publish");
    setMessage(null);
    try {
      await api("/website/publish", { method: "POST" });
      setMessage({ kind: "ok", text: L("تم النشر — الموقع اتحدث", "Published — the site is updated") });
      refreshAll();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر النشر", "Could not publish") });
    } finally {
      setBusy("");
    }
  };

  const rollbackTo = async (versionId) => {
    setBusy(`rollback-${versionId}`);
    setMessage(null);
    try {
      await api("/website/rollback", {
        method: "POST",
        body: JSON.stringify({ version_id: versionId }),
      });
      setMessage({ kind: "ok", text: L("تم الرجوع للنسخة المختارة", "Rolled back to the chosen version") });
      refreshAll();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر الرجوع", "Could not roll back") });
    } finally {
      setBusy("");
    }
  };

  if (!website) return null;
  const workingTree = content?.draft ?? content?.published;

  const renderListField = (section, f, edit) => {
    // List fields (faq items, feature cards, branch cards): repeatable rows
    // of flat inputs. The buffer holds the WHOLE array — one edit replaces it.
    const current = Array.isArray(edit[f.name])
      ? edit[f.name]
      : (section.props?.[f.name] ?? []);
    const setItems = (next) =>
      setSectionEdits((prev) => ({ ...prev, [section.id]: { ...edit, [f.name]: next } }));
    const blank = Object.fromEntries(f.item_fields.map((sf) => [sf.name, ""]));
    return (
      <div className="sm:col-span-2">
        <span className="mb-1 block text-xs font-medium" dir="ltr">
          {f.name}
          {f.required ? <span className="text-red-500"> *</span> : null}
        </span>
        <div className="space-y-2">
          {current.map((item, idx) => (
            <div key={idx} className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/20 p-2">
              {f.item_fields.map((sf) => (
                <input
                  key={sf.name}
                  value={item?.[sf.name] ?? ""}
                  placeholder={sf.name}
                  onChange={(e) =>
                    setItems(
                      current.map((it, i) => (i === idx ? { ...it, [sf.name]: e.target.value } : it)),
                    )
                  }
                  className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-primary/30"
                />
              ))}
              <button
                type="button"
                onClick={() => setItems(current.filter((_, i) => i !== idx))}
                className="rounded-md border px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                aria-label={L("حذف العنصر", "Remove item")}
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setItems([...current, { ...blank }])}
          className="mt-2 rounded-md border px-2.5 py-1.5 text-xs font-medium hover:bg-accent"
        >
          + {L("إضافة عنصر", "Add item")}
        </button>
      </div>
    );
  };

  const renderSection = (pageSlug, section) => {
    const fields = schemaFor(section.type);
    const edit = sectionEdits[section.id] ?? {};
    const label = SECTION_TYPE_LABELS[section.type]?.[isAr ? 0 : 1] ?? section.type;
    return (
      <div key={section.id} className="rounded-lg border p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
          <span className="text-[10px] text-muted-foreground" dir="ltr">
            {pageSlug} · {section.type}
          </span>
        </div>
        {fields.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            {L(
              "القسم ده محتواه من الكتالوج أو مش قابل للتحرير في النسخة دي.",
              "This section's content comes from the catalog or is not editable in this release.",
            )}
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {fields.map((f) => {
              if (f.type === "list") return renderListField(section, f, edit);
              const value = edit[f.name] ?? section.props?.[f.name] ?? "";
              const long = String(section.props?.[f.name] ?? "").length > 60 || f.name === "content";
              return (
                <label key={f.name} className={`block ${long ? "sm:col-span-2" : ""}`}>
                  <span className="mb-1 block text-xs font-medium" dir="ltr">
                    {f.name}
                    {f.required ? <span className="text-red-500"> *</span> : null}
                  </span>
                  {long ? (
                    <textarea
                      rows={3}
                      value={value}
                      onChange={(e) =>
                        setSectionEdits((prev) => ({ ...prev, [section.id]: { ...edit, [f.name]: e.target.value } }))
                      }
                      className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
                    />
                  ) : (
                    <input
                      value={value}
                      onChange={(e) =>
                        setSectionEdits((prev) => ({ ...prev, [section.id]: { ...edit, [f.name]: e.target.value } }))
                      }
                      className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
                    />
                  )}
                </label>
              );
            })}
          </div>
        )}
        {fields.length > 0 && sectionEdits[section.id] !== undefined ? (
          <button
            type="button"
            onClick={() => saveSection(section.id, section.type, section.props)}
            disabled={busy === `section-${section.id}`}
            className="mt-3 inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            {busy === `section-${section.id}` ? L("جارٍ الحفظ…", "Saving…") : L("حفظ في المسودة", "Save to draft")}
          </button>
        ) : null}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {message ? (
        <div role="status"
          className={`rounded-lg border p-3 text-sm ${
            message.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-800"
          }`}
        >
          {message.text}
        </div>
      ) : null}

      <SectionCard
        title={L("حالة الموقع", "Website status")}
        action={
          <Badge tone={website.published ? "default" : "secondary"}>
            {website.published ? L("منشور", "Published") : L("غير منشور", "Not published")}
          </Badge>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex items-center gap-3">
            <Globe className="h-5 w-5 text-muted-foreground" />
            <div>
              <div className="text-sm font-medium">{website.name}</div>
              <div className="text-xs text-muted-foreground" dir="ltr">
                /{website.slug}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Rocket className="h-5 w-5 text-muted-foreground" />
            <div>
              <div className="text-sm font-medium">{L("التصميم", "Design")}</div>
              <div className="text-xs text-muted-foreground" dir="ltr">
                {website.template_id}
              </div>
            </div>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {website.published ? (
            <a
              href={website.live_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent"
            >
              <ExternalLink className="h-4 w-4" />
              {L("عرض الموقع", "View live site")}
            </a>
          ) : null}
          <button
            type="button"
            onClick={publish}
            disabled={busy === "publish" || busy === "load"}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            <Rocket className="h-4 w-4" />
            {busy === "publish" ? L("جارٍ النشر…", "Publishing…") : L("نشر التحديثات", "Publish updates")}
          </button>
          <button type="button" onClick={refreshAll} className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent">
            <RefreshCw className="h-4 w-4" />
            {L("تحديث", "Refresh")}
          </button>
        </div>
      </SectionCard>

      <SectionCard title={L("هوية الموقع — بتظهر فورًا", "Site identity — goes live immediately")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-sm font-medium">{L("اسم الموقع", "Site name")}</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
          <div>
            <span className="mb-1 block text-sm font-medium">{L("ألوان التصميم", "Design colors")}</span>
            <div className="flex flex-wrap gap-3">
              {Object.entries(tokens).map(([key, value]) => (
                <label key={key} className="flex items-center gap-2 text-xs">
                  <span dir="ltr" className="text-muted-foreground">
                    {key}
                  </span>
                  {isColorValue(value) || COLOR_TOKENS.has(key) ? (
                    <input
                      type="color"
                      value={isColorValue(value) ? value : "#000000"}
                      onChange={(e) => setTokens((prev) => ({ ...prev, [key]: e.target.value }))}
                      className="h-8 w-10 cursor-pointer rounded border"
                    />
                  ) : (
                    <input
                      value={value}
                      onChange={(e) => setTokens((prev) => ({ ...prev, [key]: e.target.value }))}
                      className="w-24 rounded-md border bg-background px-2 py-1 text-xs"
                    />
                  )}
                </label>
              ))}
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={saveIdentity}
          disabled={busy === "identity"}
          className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Paintbrush className="h-4 w-4" />
          {busy === "identity" ? L("جارٍ الحفظ…", "Saving…") : L("حفظ الهوية", "Save identity")}
        </button>
      </SectionCard>

      <SectionCard
        title={
          content?.draft
            ? L("محتوى المسودة — ينشر بضغطة", "Draft content — one click to publish")
            : L("المحتوى المنشور", "Published content")
        }
      >
        {busy === "load" ? (
          <div className="animate-pulse space-y-3">
            <div className="h-4 w-1/4 rounded bg-muted" />
            <div className="h-20 rounded bg-muted" />
          </div>
        ) : (
          (workingTree?.pages ?? []).map((page) => (
            <div key={page.id} className="mt-4 first:mt-0">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold">{page.title}</h3>
                <span className="text-xs text-muted-foreground" dir="ltr">
                  /{page.slug}
                </span>
              </div>
              <div className="space-y-3">
                {page.sections.map((section) => renderSection(page.slug, section))}
              </div>
            </div>
          ))
        )}
      </SectionCard>

      <SectionCard title={L("سجل النسخ", "Version history")}>
        <div className="space-y-2">
          {versions.map((v) => (
            <div key={v.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3">
              <div className="flex items-center gap-3">
                <History className="h-4 w-4 text-muted-foreground" />
                <div>
                  <div className="text-sm font-medium">{v.label}</div>
                  <div className="text-xs text-muted-foreground">
                    {v.published_at ? new Date(v.published_at).toLocaleString() : "—"}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={v.status === "published" ? "default" : v.status === "draft" ? "warning" : "muted"}>
                  {v.status === "published"
                    ? L("منشورة", "Published")
                    : v.status === "draft"
                      ? L("مسودة", "Draft")
                      : L("مؤرشفة", "Archived")}
                </Badge>
                {v.status !== "draft" && v.id !== content?.published?.version?.id ? (
                  <button
                    type="button"
                    onClick={() => rollbackTo(v.id)}
                    disabled={busy === `rollback-${v.id}`}
                    className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
                  >
                    {L("ارجع لها", "Restore")}
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
