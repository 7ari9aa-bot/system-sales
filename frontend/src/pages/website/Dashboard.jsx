import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Image as ImageIcon,
  Paintbrush,
  RefreshCw,
  Rocket,
  Save,
  Settings as SettingsIcon,
  Upload,
} from "lucide-react";
import { Badge, SectionCard } from "@/components/dashboard/ui";
import { api, apiUrl } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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
  features: ["الوعود والمميزات", "Features"],
  steps: ["خطوات الشراء", "Steps"],
  branches: ["الفروع", "Branches"],
};

const COLOR_TOKENS = new Set(["primary", "background", "secondary", "accent"]);

function isColorValue(value) {
  return /^#[0-9a-fA-F]{3,8}$/.test(String(value ?? ""));
}

export default function Dashboard() {
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const L = (ar, en) => (isAr ? ar : en);

  const [content, setContent] = useState(null);
  const [schema, setSchema] = useState(null);
  const [versions, setVersions] = useState([]);
  const [overview, setOverview] = useState(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState("content");

  const [name, setName] = useState("");
  const [tokens, setTokens] = useState({});
  const [sectionEdits, setSectionEdits] = useState({});
  const logoRef = useRef(null);

  const refreshAll = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    setBusy("load");
    Promise.all([
      api("/website/overview"),
      api("/website/content"),
      api("/website/editor-schema"),
      api("/website/versions"),
    ])
      .then(([ov, c, sc, v]) => {
        if (!alive) return;
        setOverview(ov);
        setContent(c);
        setSchema(sc?.sections ?? []);
        setVersions(v?.versions ?? []);
        if (ov?.website) {
          setName(ov.website.name);
          setTokens(ov.website.theme_tokens ?? {});
        }
      })
      .catch((err) => {
        if (alive) setMessage({ kind: "err", text: err?.message || L("تعذر التحميل", "Could not load") });
      })
      .finally(() => alive && setBusy(""));
    return () => {
      alive = false;
    };
  }, [attempt]);

  const saveIdentity = async () => {
    setBusy("identity");
    setMessage(null);
    try {
      await api("/website/content/identity", {
        method: "POST",
        body: JSON.stringify({ name, theme_tokens: tokens }),
      });
      setMessage({ kind: "ok", text: L("تم الحفظ — ظهر على الموقع", "Saved — live on the site") });
      refreshAll();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر الحفظ", "Could not save") });
    } finally {
      setBusy("");
    }
  };

  const saveSection = async (sectionId, currentProps) => {
    const edit = sectionEdits[sectionId];
    if (edit === undefined) return;
    setBusy(`section-${sectionId}`);
    setMessage(null);
    try {
      await api("/website/content/section", {
        method: "POST",
        body: JSON.stringify({ section_id: sectionId, props: { ...currentProps, ...edit } }),
      });
      setMessage({ kind: "ok", text: L("اتحفظ في المسودة — انشر عشان يظهر", "Saved to draft — publish to go live") });
      setSectionEdits((prev) => ({ ...prev, [sectionId]: undefined }));
      refreshAll();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر الحفظ", "Could not save") });
    } finally {
      setBusy("");
    }
  };

  const publish = async () => {
    setBusy("publish");
    setMessage(null);
    try {
      await api("/website/publish", { method: "POST" });
      setMessage({ kind: "ok", text: L("تم النشر", "Published") });
      refreshAll();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر النشر", "Could not publish") });
    } finally {
      setBusy("");
    }
  };

  const rollbackTo = async (versionId) => {
    setBusy(`rb-${versionId}`);
    setMessage(null);
    try {
      await api("/website/rollback", { method: "POST", body: JSON.stringify({ version_id: versionId }) });
      setMessage({ kind: "ok", text: L("تم الرجوع", "Rolled back") });
      refreshAll();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر الرجوع", "Could not roll back") });
    } finally {
      setBusy("");
    }
  };

  const uploadLogo = async (file) => {
    if (!file) return;
    setBusy("logo");
    setMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(apiUrl("/website/images/upload"), {
        method: "POST",
        headers: { "X-CSRF-Token": document.cookie.match(/csrf_token=([^;]+)/)?.[1] ?? "" },
        body: form,
        credentials: "include",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.error?.message || `HTTP ${res.status}`);
      }
      const data = await res.json();
      if (data?.url) {
        setTokens((prev) => ({ ...prev, logo_url: data.url }));
      }
      setMessage({ kind: "ok", text: L("تم رفع الصورة", "Image uploaded") });
      refreshAll();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر الرفع", "Upload failed") });
    } finally {
      setBusy("");
    }
  };

  const website = overview?.website;
  const workingTree = content?.draft ?? content?.published;
  const schemaFor = (type) => schema?.find((s) => s.type === type)?.fields ?? [];

  const renderListField = (section, f, edit) => {
    const current = Array.isArray(edit[f.name]) ? edit[f.name] : (section.props?.[f.name] ?? []);
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
                    setItems(current.map((it, i) => (i === idx ? { ...it, [sf.name]: e.target.value } : it)))
                  }
                  className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-primary/30"
                />
              ))}
              <button
                type="button"
                onClick={() => setItems(current.filter((_, i) => i !== idx))}
                className="rounded-md border px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
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
          + {L("إضافة", "Add")}
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
          <span className="text-[10px] text-muted-foreground" dir="ltr">{pageSlug} · {section.type}</span>
        </div>
        {fields.length === 0 ? (
          <p className="text-xs text-muted-foreground">{L("غير قابل للتحرير في النسخة دي.", "Not editable in this release.")}</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {fields.map((f) => {
              if (f.type === "list") return renderListField(section, f, edit);
              const value = edit[f.name] ?? section.props?.[f.name] ?? "";
              const long = String(section.props?.[f.name] ?? "").length > 60 || f.name === "content";
              return (
                <label key={f.name} className={`block ${long ? "sm:col-span-2" : ""}`}>
                  <span className="mb-1 block text-xs font-medium" dir="ltr">
                    {f.name}{f.required ? <span className="text-red-500"> *</span> : null}
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
            onClick={() => saveSection(section.id, section.props)}
            disabled={busy === `section-${section.id}`}
            className="mt-3 inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            {L("حفظ في المسودة", "Save to draft")}
          </button>
        ) : null}
      </div>
    );
  };

  if (!website) return null;

  return (
    <div className="space-y-6">
      {message ? (
        <div role="status" className={`rounded-lg border p-3 text-sm ${
          message.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-red-200 bg-red-50 text-red-800"
        }`}>
          {message.text}
        </div>
      ) : null}

      <SectionCard
        title={L("إدارة الموقع", "Website management")}
        action={
          <div className="flex gap-2">
            <Badge tone={website.published ? "default" : "secondary"}>
              {website.published ? L("منشور", "Published") : L("غير منشور", "Not published")}
            </Badge>
            {website.published ? (
              <a href={website.live_url} target="_blank" rel="noopener noreferrer" className="text-sm text-primary hover:underline">
                {L("عرض الموقع", "View site")}
              </a>
            ) : null}
          </div>
        }
      >
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={publish} disabled={busy === "publish" || busy === "load"}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            <Rocket className="h-4 w-4" />
            {busy === "publish" ? L("جارٍ النشر…", "Publishing…") : L("نشر التحديثات", "Publish updates")}
          </button>
          <button type="button" onClick={refreshAll} className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent">
            <RefreshCw className="h-4 w-4" />{L("تحديث", "Refresh")}
          </button>
        </div>
      </SectionCard>

      <div className="flex gap-1.5 rounded-xl border bg-card p-1.5">
        {[
          { id: "content", label: L("المحتوى", "Content"), icon: Paintbrush },
          { id: "images", label: L("الصور", "Images"), icon: ImageIcon },
          { id: "settings", label: L("الإعدادات", "Settings"), icon: SettingsIcon },
        ].map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-[13px] font-medium transition-colors ${
              tab === t.id ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-surface"
            }`}>
            <t.icon className="h-4 w-4" />{t.label}
          </button>
        ))}
      </div>

      {tab === "content" ? (
        <>
          <SectionCard title={L("هوية الموقع — يظهر فورًا", "Site identity — live immediately")}>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-sm font-medium">{L("اسم الموقع", "Site name")}</span>
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30" />
              </label>
              <div>
                <span className="mb-1 block text-sm font-medium">{L("ألوان التصميم", "Colors")}</span>
                <div className="flex flex-wrap gap-3">
                  {Object.entries(tokens).map(([key, value]) => (
                    <label key={key} className="flex items-center gap-2 text-xs">
                      <span dir="ltr" className="text-muted-foreground">{key}</span>
                      <input type="color" value={isColorValue(value) ? value : "#000000"}
                        onChange={(e) => setTokens((prev) => ({ ...prev, [key]: e.target.value }))}
                        className="h-8 w-10 cursor-pointer rounded border" />
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <button type="button" onClick={saveIdentity} disabled={busy === "identity"}
              className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
              <Paintbrush className="h-4 w-4" />
              {busy === "identity" ? L("جارٍ الحفظ…", "Saving…") : L("حفظ الهوية", "Save identity")}
            </button>
          </SectionCard>

          {workingTree?.pages?.map((page) => (
            <SectionCard key={page.id} title={page.title}>
              <div className="space-y-3">
                {page.sections.map((section) => renderSection(page.slug, section))}
              </div>
            </SectionCard>
          ))}
        </>
      ) : null}

      {tab === "images" ? (
        <SectionCard title={L("الصور", "Images")}>
          <div className="space-y-4">
            <div>
              <span className="mb-2 block text-sm font-medium">{L("لوجو الموقع", "Site logo")}</span>
              <div className="flex items-center gap-3">
                <input type="file" accept="image/*" ref={logoRef} className="hidden"
                  onChange={(e) => { setLogoFile(e.target.files?.[0]); uploadLogo(e.target.files?.[0]); }} />
                <button type="button" onClick={() => logoRef.current?.click()} disabled={busy === "logo"}
                  className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50">
                  <Upload className="h-4 w-4" />
                  {busy === "logo" ? L("جارٍ الرفع…", "Uploading…") : L("رفع لوجو", "Upload logo")}
                </button>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              {L("صور المنتجات بتتدار من صفحة المنتجات في الكتالوج وتظهر على الموقع تلقائيًا.",
                 "Product images are managed from the catalog Products page and appear on the site automatically.")}
            </p>
          </div>
        </SectionCard>
      ) : null}

      {tab === "settings" ? (
        <SectionCard title={L("الإعدادات", "Settings")}>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {L("اسم الموقع: ", "Site name: ")}{website.name}
            </p>
            <p className="text-sm text-muted-foreground" dir="ltr">/{website.slug}</p>
            <p className="text-sm text-muted-foreground">{L("التصميم: ", "Template: ")}{website.template_id}</p>
          </div>
        </SectionCard>
      ) : null}

      <SectionCard title={L("سجل النسخ", "Version history")}>
        <div className="space-y-2">
          {versions.map((v) => (
            <div key={v.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3">
              <div className="flex items-center gap-3">
                <div>
                  <div className="text-sm font-medium">{v.label}</div>
                  <div className="text-xs text-muted-foreground">
                    {v.published_at ? new Date(v.published_at).toLocaleString() : "—"}
                  </div>
                </div>
              </div>
              <Badge tone={v.status === "published" ? "default" : v.status === "draft" ? "warning" : "muted"}>
                {v.status === "published" ? L("منشورة", "Published") : v.status === "draft" ? L("مسودة", "Draft") : L("مؤرشفة", "Archived")}
              </Badge>
              {v.status !== "draft" && v.id !== content?.published?.version?.id ? (
                <button type="button" onClick={() => rollbackTo(v.id)} disabled={busy === `rb-${v.id}`}
                  className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50">
                  {L("ارجع لها", "Restore")}
                </button>
              ) : null}
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
